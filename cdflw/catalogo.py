"""cdflw: Databricks.

Guarda de SQL (so leitura, mascaramento), Unity Catalog (snapshot, linhagem, tabelas sob demanda,
cluster), e os testes no dado (perfil, testar-regra, exemplos, dominio, sobreposicao).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from typing import Any, Callable

from . import nucleo

# ==========================================================================================
# sql_guarda: Guarda do SQL que o agente propoe e mascaramento de valores.
# ==========================================================================================



# REPLACE fica de fora porque e funcao de texto; SET/USE nao cabem depois de um SELECT sem ';'.
_PROIBIDO = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|VACUUM|OPTIMIZE)\b", re.I)


class SqlInvalido(ValueError):
    pass


def validar_sql(sql: str) -> str:
    """Devolve o SQL limpo ou levanta SqlInvalido. So SELECT/WITH, um comando, sem DML/DDL."""
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        raise SqlInvalido("SQL vazio")
    if ";" in s:
        raise SqlInvalido("um comando por vez (encontrei ';')")
    if not re.match(r"^(SELECT|WITH)\b", s, re.I):
        raise SqlInvalido("so SELECT ou WITH sao permitidos")
    # procura no texto bruto, comentarios inclusive: palavra de escrita nao tem o que fazer numa leitura
    m = _PROIBIDO.search(s)
    if m:
        raise SqlInvalido(f"palavra nao permitida em consulta de leitura: {m.group(0).upper()}")
    return s


def validar_predicado(pred: str) -> str:
    """Predicado de WHERE: sem ponto e virgula, sem palavras de escrita, sem subconsulta que escreva."""
    p = (pred or "").strip()
    if not p:
        raise SqlInvalido("predicado vazio")
    if ";" in p:
        raise SqlInvalido("predicado nao pode ter ';'")
    m = _PROIBIDO.search(p)
    if m:
        raise SqlInvalido(f"palavra nao permitida no predicado: {m.group(0).upper()}")
    return p


def mascarar_valor(valor: str) -> str:
    """Digitos viram 9, letras viram X, tamanho e pontuacao preservados. 'Rua 12, Ap 3B' -> 'XXX 99, XX 9X'."""
    if valor is None:
        return ""
    s = str(valor)
    s = re.sub(r"[0-9]", "9", s)
    s = re.sub(r"[A-Za-zÀ-ÿ]", "X", s)
    return s


def fonte_amostrada(tabela: str, total: int | None, max_linhas: int) -> str:
    """FROM com TABLESAMPLE quando a tabela e grande. Percentual calculado para ~max_linhas."""
    if total and max_linhas and total > max_linhas:
        pct = max(0.01, min(100.0, 100.0 * max_linhas / total))
        return f"{tabela} TABLESAMPLE ({pct:.2f} PERCENT)"
    return tabela


def identificador(nome: str) -> str:
    """So aceita identificadores simples (a.b.c ou a_b) para entrar numa consulta montada pelo codigo."""
    if not re.fullmatch(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}", nome or ""):
        raise SqlInvalido(f"identificador invalido: {nome!r}")
    return nome


# ==========================================================================================
# uc: Unity Catalog: snapshot de metadados, tabelas sob demanda, linhagem e execucao de SQL.
# ==========================================================================================




Linhas = list[list[str]]


def _cliente(cfg: nucleo.Config):
    from databricks.sdk import WorkspaceClient  # import tardio: so quem fala com o Databricks precisa

    return WorkspaceClient(profile=cfg.profile)


def _colunas_de(info) -> list[dict[str, str]]:
    cols = []
    for c in (getattr(info, "columns", None) or []):
        cols.append({"nome": c.name, "tipo": getattr(c, "type_text", "") or str(getattr(c, "type_name", "") or ""), "comentario": c.comment or ""})
    return cols


# ---------------------------------------------------------------------------
# Snapshot do schema principal (REST)
# ---------------------------------------------------------------------------
def listar_tabelas(cfg: nucleo.Config, cliente=None, progresso: Callable[[str], None] | None = None) -> dict[str, Any]:
    w = cliente or _cliente(cfg)
    tabelas: dict[str, Any] = {}
    for t in w.tables.list(catalog_name=cfg.catalogo, schema_name=cfg.schema):
        info = t
        if not getattr(t, "columns", None):
            info = w.tables.get(full_name=f"{cfg.catalogo}.{cfg.schema}.{t.name}")
        tabelas[t.name] = {"comentario": info.comment or "", "tipo_tabela": str(getattr(info, "table_type", "") or ""), "colunas": _colunas_de(info)}
        if progresso:
            progresso(f"  {t.name}: {len(tabelas[t.name]['colunas'])} colunas")
    corpo = json.dumps(tabelas, sort_keys=True, ensure_ascii=False)
    return {
        "snapshot_id": dt.date.today().isoformat() + "-" + hashlib.sha256(corpo.encode("utf-8")).hexdigest()[:8],
        "gerado_em": dt.datetime.now().isoformat(timespec="seconds"),
        "catalogo": cfg.catalogo,
        "schema": cfg.schema,
        "tabelas": tabelas,
    }


# ---------------------------------------------------------------------------
# Execucao de SQL (warehouse -> cluster -> connect), tolerante a falha
# ---------------------------------------------------------------------------
def _sql_warehouse(w, cfg: nucleo.Config, sql: str) -> Linhas:
    r = w.statement_execution.execute_statement(warehouse_id=cfg.warehouse_id, statement=sql, wait_timeout="50s")
    while r.status and r.status.state and r.status.state.value in ("PENDING", "RUNNING"):
        time.sleep(3)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status and r.status.state and r.status.state.value == "FAILED":
        raise RuntimeError(getattr(getattr(r.status, "error", None), "message", "statement FAILED"))
    if not r.result or not r.result.data_array:
        return []
    return [[("" if x is None else str(x)) for x in linha] for linha in r.result.data_array]


class ClusterDesligado(RuntimeError):
    """O cluster esta parado e a configuracao nao permite ligar automaticamente."""


class ClusterIniciando(RuntimeError):
    """O cluster esta subindo; passou o tempo maximo de espera deste comando. Rode de novo."""


ESTADOS_RODANDO = ("RUNNING",)
ESTADOS_SUBINDO = ("PENDING", "RESTARTING", "RESIZING")


def estado_cluster(cfg: nucleo.Config, cliente=None) -> dict[str, str]:
    """{'id','nome','estado','mensagem'} via REST (nao liga nada)."""
    if not cfg.cluster_id:
        return {"id": "", "nome": "", "estado": "SEM_CLUSTER", "mensagem": "cluster_id vazio: python -m cdflw recursos / configurar --local --cluster-nome ..."}
    w = cliente or _cliente(cfg)
    c = w.clusters.get(cluster_id=cfg.cluster_id)
    st = getattr(c.state, "value", c.state)
    return {"id": cfg.cluster_id, "nome": c.cluster_name or "", "estado": str(st or "?"), "mensagem": str(getattr(c, "state_message", "") or "")}


def ligar_cluster(cfg: nucleo.Config, cliente=None) -> dict[str, str]:
    """Pede para ligar e volta na hora (nao espera)."""
    w = cliente or _cliente(cfg)
    e = estado_cluster(cfg, w)
    if e["estado"] in ESTADOS_RODANDO or e["estado"] in ESTADOS_SUBINDO:
        return e
    w.clusters.start(cluster_id=cfg.cluster_id)  # retorna um Wait; nao chamamos .result()
    return estado_cluster(cfg, w)


def esperar_cluster(cfg: nucleo.Config, cliente=None, max_s: int | None = None, progresso: Callable[[str], None] | None = None,
                    dormir: Callable[[float], None] | None = None) -> dict[str, str]:
    """Espera ate RUNNING, imprimindo o estado a cada `intervalo_poll_s`. Devolve o ultimo estado (pode nao ser RUNNING)."""
    dormir = dormir or time.sleep  # resolvido na chamada, para os testes poderem trocar time.sleep
    w = cliente or _cliente(cfg)
    max_s = cfg.espera_cluster_s if max_s is None else max_s
    passo = max(5, cfg.intervalo_poll_s)
    gasto = 0
    e = estado_cluster(cfg, w)
    while e["estado"] not in ESTADOS_RODANDO and gasto < max_s:
        if progresso:
            progresso(f"  [{gasto // 60:02d}:{gasto % 60:02d}] cluster {e['nome'] or e['id']}: {e['estado']}" + (f" ({e['mensagem']})" if e["mensagem"] else ""))
        if e["estado"] not in ESTADOS_SUBINDO:
            break  # TERMINATED/ERROR: esperar nao resolve
        dormir(passo)
        gasto += passo
        e = estado_cluster(cfg, w)
    return e


def garantir_cluster(cfg: nucleo.Config, cliente=None, progresso: Callable[[str], None] | None = None, max_s: int | None = None) -> dict[str, str]:
    """RUNNING ou excecao clara. Liga se `auto_ligar_cluster`; espera no maximo `espera_cluster_s`."""
    w = cliente or _cliente(cfg)
    e = estado_cluster(cfg, w)
    if e["estado"] in ESTADOS_RODANDO:
        return e
    if e["estado"] not in ESTADOS_SUBINDO:
        if not cfg.auto_ligar_cluster:
            raise ClusterDesligado(f"cluster {e['nome'] or e['id']} esta {e['estado']}. Ligue com: python -m cdflw cluster --ligar (e espere com --esperar)")
        if progresso:
            progresso(f"  cluster {e['nome'] or e['id']} esta {e['estado']}: pedindo para ligar (all-purpose leva alguns minutos)")
        ligar_cluster(cfg, w)
    e = esperar_cluster(cfg, w, max_s, progresso)
    if e["estado"] in ESTADOS_RODANDO:
        return e
    if e["estado"] in ESTADOS_SUBINDO:
        raise ClusterIniciando(f"cluster {e['nome'] or e['id']} ainda {e['estado']} apos {max_s if max_s is not None else cfg.espera_cluster_s}s. Rode: python -m cdflw cluster --esperar  e repita este comando quando estiver RUNNING")
    raise ClusterDesligado(f"cluster {e['nome'] or e['id']} ficou em {e['estado']}: {e['mensagem'] or 'veja o Databricks'}")


def _sql_cluster(w, cfg: nucleo.Config, sql: str, progresso) -> Linhas:
    from databricks.sdk.service.compute import Language

    garantir_cluster(cfg, w, progresso)
    ctx = w.command_execution.create(cluster_id=cfg.cluster_id, language=Language.SQL).result()
    try:
        res = w.command_execution.execute(cluster_id=cfg.cluster_id, context_id=ctx.id, language=Language.SQL, command=sql).result()
        results = res.results
        if results is not None and str(getattr(results, "result_type", "")).lower().endswith("error"):
            raise RuntimeError(getattr(results, "cause", None) or getattr(results, "summary", None) or "erro no cluster")
        dados = getattr(results, "data", None) or []
        return [[("" if x is None else str(x)) for x in linha] for linha in dados]
    finally:
        try:
            w.command_execution.destroy(cluster_id=cfg.cluster_id, context_id=ctx.id)
        except Exception:
            pass


def _sql_connect(cfg: nucleo.Config, sql: str) -> Linhas:
    from databricks.connect import DatabricksSession  # type: ignore

    if estado_cluster(cfg)["estado"] not in ESTADOS_RODANDO:
        raise ClusterIniciando("cluster nao esta RUNNING; Databricks Connect bloquearia sem aviso")
    spark = DatabricksSession.builder.profile(cfg.profile).clusterId(cfg.cluster_id).getOrCreate()
    return [[("" if x is None else str(x)) for x in linha] for linha in spark.sql(sql).collect()]


def executar_sql(cfg: nucleo.Config, sql: str, cliente=None, progresso: Callable[[str], None] | None = None,
                 executor: Callable[[str], Linhas] | None = None) -> tuple[Linhas, list[str], str]:
    """Devolve (linhas, erros, via). `via` diz por onde rodou ('warehouse', 'cluster', 'connect', 'executor', '')."""
    erros: list[str] = []
    tentativas: list[tuple[str, Callable[[], Linhas]]] = []
    if executor:
        tentativas.append(("executor", lambda: executor(sql)))
    else:
        w = cliente or _cliente(cfg)
        if cfg.warehouse_id:
            tentativas.append(("warehouse", lambda: _sql_warehouse(w, cfg, sql)))
        if cfg.cluster_id:
            tentativas.append(("cluster", lambda: _sql_cluster(w, cfg, sql, progresso)))
            tentativas.append(("connect", lambda: _sql_connect(cfg, sql)))
        if not tentativas:
            erros.append("sem warehouse_id nem cluster_id configurados (python -m cdflw recursos / configurar --local ...)")
    pendente: Exception | None = None
    for nome, fn in tentativas:
        try:
            return fn(), erros, nome
        except (ClusterDesligado, ClusterIniciando) as e:
            pendente = e  # tenta as outras vias; se nenhuma servir, o chamador precisa saber que e "espere e repita"
            erros.append(f"{nome}: {e}")
        except Exception as e:  # noqa: BLE001 - qualquer outra falha vira aviso, nunca bloqueio
            erros.append(f"{nome}: {type(e).__name__}: {e}")
    if pendente is not None:
        raise pendente
    return [], erros, ""


# ---------------------------------------------------------------------------
# Linhagem
# ---------------------------------------------------------------------------
SQL_LINHAGEM = """
SELECT source_table_schema, source_table_name, source_column_name,
       target_table_name, target_column_name, count(*) AS n
FROM system.access.column_lineage
WHERE target_table_catalog = '{catalogo}' AND target_table_schema = '{schema}'
  AND source_table_name IS NOT NULL AND source_column_name IS NOT NULL
GROUP BY 1,2,3,4,5
"""

SQL_LINHAGEM_TABELA = """
SELECT source_table_schema, source_table_name, source_column_name,
       target_table_name, target_column_name, count(*) AS n
FROM system.access.column_lineage
WHERE target_table_catalog = '{catalogo}' AND target_table_schema = '{schema}' AND target_table_name = '{tabela}'
  AND source_table_name IS NOT NULL AND source_column_name IS NOT NULL
GROUP BY 1,2,3,4,5
"""


def _agrupar_linhagem(linhas: Linhas, prefixo_alvo: str = "") -> dict[str, list[dict[str, Any]]]:
    por_alvo: dict[str, list[dict[str, Any]]] = {}
    for l in linhas:
        if len(l) < 5:
            continue
        s_schema, s_tab, s_col, t_tab, t_col = l[:5]
        n = int(float(l[5])) if len(l) > 5 and l[5] not in ("", "None") else 1
        chave = f"{prefixo_alvo}{t_tab}.{t_col}".lower()
        por_alvo.setdefault(chave, []).append({"origem": f"{s_schema}.{s_tab}.{s_col}".lower(), "n": n})
    return por_alvo


def consultar_linhagem(cfg: nucleo.Config, cliente=None, progresso: Callable[[str], None] | None = None,
                       executor: Callable[[str], Linhas] | None = None) -> dict[str, Any]:
    sql = SQL_LINHAGEM.format(catalogo=cfg.catalogo, schema=cfg.schema)
    try:
        linhas, erros, via = executar_sql(cfg, sql, cliente, progresso, executor)
    except (ClusterDesligado, ClusterIniciando) as e:
        linhas, erros, via = [], [f"linhagem adiada: {e}"], ""
    if progresso and via:
        progresso(f"  linhagem via {via}: {len(linhas)} relacoes")
    return {"gerado_em": dt.datetime.now().isoformat(timespec="seconds"), "relacoes": _agrupar_linhagem(linhas), "erros": erros}


# ---------------------------------------------------------------------------
# Tabelas sob demanda (fora do schema principal)
# ---------------------------------------------------------------------------
SUFIXOS_COPIA = ("_bckp", "_bkp", "_backup", "_hist", "_previa", "_prev", "_hive", "_old", "_tmp", "_temp")

SQL_HOMONIMAS = """
SELECT table_catalog, table_schema, table_name, table_type
FROM system.information_schema.tables
WHERE lower(table_name) = '{nome}'
"""

SQL_USO = """
SELECT lower(t.table_name) AS tabela, count(*) AS n
FROM system.query.history q
LATERAL VIEW explode(q.read_tables) AS t(table_name)
WHERE q.start_time >= current_date() - INTERVAL {dias} DAYS
  AND lower(t.table_name) IN ({lista})
GROUP BY 1
"""


def obter_tabela(cfg: nucleo.Config, fqn: str, cliente=None) -> dict[str, Any] | None:
    """Metadados de uma tabela pelo nome qualificado (REST). None se nao existir."""
    w = cliente or _cliente(cfg)
    try:
        info = w.tables.get(full_name=fqn)
    except Exception as e:  # noqa: BLE001
        if "NOT_FOUND" in str(e).upper() or "does not exist" in str(e).lower() or "not found" in str(e).lower():
            return None
        raise
    cat, sch, nome = fqn.split(".", 2)
    return {"fqn": fqn, "catalogo": cat, "schema": sch, "nome": nome, "comentario": info.comment or "",
            "tipo_tabela": str(getattr(info, "table_type", "") or ""), "colunas": _colunas_de(info),
            "incluida_em": dt.datetime.now().isoformat(timespec="seconds")}


def buscar_homonimas(cfg: nucleo.Config, nome: str, cliente=None, executor=None, progresso=None) -> tuple[list[str], list[str]]:
    """FQNs de tabelas com o mesmo nome em outros schemas.

    Metadado nunca liga cluster: lista por REST os schemas do catalogo (e os de `schemas_busca`).
    O information_schema por SQL so entra quando ha SQL warehouse configurado (sobe em segundos).
    """
    nome = nome.lower()
    erros: list[str] = []
    if cfg.warehouse_id or executor is not None:
        try:
            linhas, erros, _via = executar_sql(cfg, SQL_HOMONIMAS.format(nome=nome.replace("'", "")), cliente, progresso, executor)
            if linhas:
                return [f"{l[0]}.{l[1]}.{l[2]}" for l in linhas if len(l) >= 3], erros
        except (ClusterDesligado, ClusterIniciando) as e:
            erros.append(str(e))
    achadas: list[str] = []
    w = cliente or _cliente(cfg)
    alvos: list[tuple[str, str]] = []
    try:
        for sc in w.schemas.list(catalog_name=cfg.catalogo):
            if sc.name and sc.name.lower() != "information_schema":
                alvos.append((cfg.catalogo, sc.name))
    except Exception as e:  # noqa: BLE001
        erros.append(f"schemas.list {cfg.catalogo}: {type(e).__name__}: {e}")
    for fq_schema in cfg.schemas_busca:
        if "." in fq_schema:
            cat, sch = fq_schema.split(".", 1)
            if (cat, sch) not in alvos:
                alvos.append((cat, sch))
    for cat, sch in alvos:
        try:
            for t in w.tables.list(catalog_name=cat, schema_name=sch):
                if (t.name or "").lower() == nome:
                    achadas.append(f"{cat}.{sch}.{t.name}")
        except Exception as e:  # noqa: BLE001
            erros.append(f"tables.list {cat}.{sch}: {type(e).__name__}: {e}")
    return achadas, erros


def uso_recente(cfg: nucleo.Config, fqns: list[str], cliente=None, executor=None, progresso=None) -> dict[str, int]:
    """Quantas consultas leram cada tabela nos ultimos N dias (system.query.history). Vazio se nao houver acesso."""
    if not fqns or not cfg.usar_query_history or not (cfg.warehouse_id or executor is not None):
        return {}
    lista = ",".join("'" + f.lower().replace("'", "") + "'" for f in fqns)
    try:
        linhas, _erros, _via = executar_sql(cfg, SQL_USO.format(dias=cfg.dias_uso, lista=lista), cliente, progresso, executor)
    except (ClusterDesligado, ClusterIniciando):
        return {}
    return {l[0]: int(float(l[1])) for l in linhas if len(l) >= 2}


def ranquear(cfg: nucleo.Config, pedida: str, candidatas: list[dict[str, Any]], uso: dict[str, int], siglas_pedido: set[str],
             grau_linhagem: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Ordena candidatas pelo que melhor se enquadra como tabela silver/gold de alto uso.

    Pontuacao (maior = melhor): nome exato pedido; schema na lista de preferidos (posicao);
    uso recente; linhagem; colunas em comum com as siglas do pedido; penalidade para sufixo de copia.
    """
    pref = [p.lower() for p in cfg.schemas_preferidos]
    saida = []
    for c in candidatas:
        fqn = c["fqn"].lower()
        nome, schema = c["nome"].lower(), c["schema"].lower()
        pts, motivos = 0.0, []
        if fqn == pedida.lower():
            pts += 100; motivos.append("nome exato pedido")
        for i, p in enumerate(pref):
            if p and (schema.endswith(p) or schema == p):
                pts += 30 - i * 5; motivos.append(f"schema preferido ({p})")
                break
        u = uso.get(fqn, 0)
        if u:
            pts += min(30, 5 + u / 10); motivos.append(f"{u} consultas em {cfg.dias_uso} dias")
        gl = (grau_linhagem or {}).get(fqn, 0)
        if gl:
            pts += min(10, gl); motivos.append(f"{gl} colunas com linhagem")
        cols = {x["nome"].upper() for x in c.get("colunas", [])}
        comum = len(cols & siglas_pedido)
        if comum:
            pts += 3 * comum; motivos.append(f"{comum} coluna(s) citadas no pedido")
        if any(nome.endswith(s) or schema.endswith(s) for s in SUFIXOS_COPIA) and not any(pedida.lower().endswith(s) for s in SUFIXOS_COPIA):
            pts -= 40; motivos.append("sufixo de copia/historico")
        saida.append({**c, "pontos": round(pts, 1), "motivos": motivos})
    saida.sort(key=lambda x: -x["pontos"])
    return saida


def incluir_tabela(cfg: nucleo.Config, fqn: str, siglas_pedido: set[str] | None = None, similares: bool = True, linhagem: bool = False,
                   cliente=None, executor=None, progresso=None) -> dict[str, Any]:
    """Busca a tabela pedida e as homonimas, ranqueia, grava nos extras. Devolve o relatorio."""
    fqn = fqn.strip().strip("`").lower()
    if fqn.count(".") != 2:
        return {"erro": f"use catalogo.schema.tabela (recebi '{fqn}')", "candidatas": []}
    w = cliente
    try:
        w = cliente or _cliente(cfg)
    except Exception as e:  # noqa: BLE001
        return {"erro": f"sem cliente Databricks: {type(e).__name__}: {e}", "candidatas": []}
    erros: list[str] = []
    pedida = obter_tabela(cfg, fqn, w)
    candidatas = [pedida] if pedida else []
    if similares:
        nomes, e2 = buscar_homonimas(cfg, fqn.split(".")[-1], w, executor, progresso)
        erros += e2
        for n in nomes:
            if n.lower() == fqn or any(c["fqn"].lower() == n.lower() for c in candidatas):
                continue
            t = obter_tabela(cfg, n, w)
            if t:
                candidatas.append(t)
    if not candidatas:
        return {"erro": f"{fqn} nao existe no catalogo e nenhuma tabela homonima foi encontrada", "candidatas": [], "erros": erros}
    uso = uso_recente(cfg, [c["fqn"] for c in candidatas], w, executor, progresso)
    rank = ranquear(cfg, fqn, candidatas, uso, {s.upper() for s in (siglas_pedido or set())})
    extras = carregar_extras(cfg)
    for c in rank:
        extras[c["fqn"].lower()] = {k: v for k, v in c.items() if k not in ("motivos",)} | {"motivos": c["motivos"]}
    lin_rel: dict[str, Any] = {}
    if linhagem:
        for c in rank[:1]:
            sql = SQL_LINHAGEM_TABELA.format(catalogo=c["catalogo"], schema=c["schema"], tabela=c["nome"])
            try:
                linhas, e3, _via = executar_sql(cfg, sql, w, progresso, executor)
            except (ClusterDesligado, ClusterIniciando) as e:
                linhas, e3 = [], [f"linhagem adiada: {e}"]
            erros += e3
            lin_rel.update(_agrupar_linhagem(linhas, prefixo_alvo=f"{c['catalogo']}.{c['schema']}."))
        if lin_rel:
            lin = carregar_linhagem(cfg)
            lin.setdefault("relacoes", {}).update(lin_rel)
            gravar_linhagem(cfg, lin)
    gravar_extras(cfg, extras)
    return {"pedida": fqn, "existe": pedida is not None, "candidatas": rank, "recomendada": rank[0]["fqn"] if rank else "",
            "ambigua": len(rank) > 1 and rank[0]["pontos"] - rank[1]["pontos"] < 15, "erros": erros, "linhagem": len(lin_rel)}


def texto_inclusao(rel: dict[str, Any]) -> list[str]:
    if rel.get("erro"):
        return [rel["erro"]] + [f"  {e}" for e in rel.get("erros", [])]
    linhas = [f"tabela pedida: {rel['pedida']} ({'existe' if rel['existe'] else 'NAO existe com esse nome exato'})"]
    for i, c in enumerate(rel["candidatas"], 1):
        linhas.append(f"  {i}. {c['fqn']}  [{c['pontos']} pts]  {len(c.get('colunas', []))} colunas  {'; '.join(c['motivos'])}")
    if rel["candidatas"]:
        linhas.append(f"recomendada: {rel['recomendada']}" + ("  (AMBIGUA: pergunte ao usuario qual usar)" if rel["ambigua"] else ""))
    if rel.get("linhagem"):
        linhas.append(f"linhagem: {rel['linhagem']} colunas com origem")
    for e in rel.get("erros", []):
        linhas.append(f"  aviso: {e}")
    linhas.append("as tabelas acima agora fazem parte do indice: campo/tabela/validar as enxergam.")
    return linhas


# ---------------------------------------------------------------------------
# Recursos (clusters, warehouses)
# ---------------------------------------------------------------------------
def listar_recursos(cfg: nucleo.Config, cliente=None) -> dict[str, list[dict[str, str]]]:
    w = cliente or _cliente(cfg)
    clusters, warehouses = [], []
    try:
        for c in w.clusters.list():
            clusters.append({"id": c.cluster_id or "", "nome": c.cluster_name or "", "estado": str(getattr(c.state, "value", c.state) or "")})
    except Exception as e:  # noqa: BLE001
        clusters.append({"id": "", "nome": f"(erro ao listar: {type(e).__name__}: {e})", "estado": ""})
    try:
        for wh in w.warehouses.list():
            warehouses.append({"id": wh.id or "", "nome": wh.name or "", "estado": str(getattr(wh.state, "value", wh.state) or "")})
    except Exception as e:  # noqa: BLE001
        warehouses.append({"id": "", "nome": f"(erro ao listar: {type(e).__name__}: {e})", "estado": ""})
    return {"clusters": clusters, "warehouses": warehouses}


def resolver_por_nome(itens: list[dict[str, str]], nome: str) -> str:
    n = nome.strip().lower()
    exatos = [i for i in itens if i["nome"].lower() == n]
    if len(exatos) == 1:
        return exatos[0]["id"]
    parciais = [i for i in itens if n in i["nome"].lower()]
    return parciais[0]["id"] if len(parciais) == 1 else ""


# ---------------------------------------------------------------------------
# Persistencia e consultas locais (o que o agente usa no dia a dia)
# ---------------------------------------------------------------------------
def _ler_json(p: Path) -> dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _gravar_json(p: Path, obj: dict[str, Any]) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def carregar_snapshot(cfg: nucleo.Config) -> dict[str, Any]:
    return _ler_json(cfg.dados / "uc" / f"{cfg.schema}.json")


def carregar_linhagem(cfg: nucleo.Config) -> dict[str, Any]:
    return _ler_json(cfg.dados / "uc" / "linhagem.json")


def carregar_extras(cfg: nucleo.Config) -> dict[str, Any]:
    return _ler_json(cfg.dados / "uc" / "extras.json")


def gravar_snapshot(cfg: nucleo.Config, snap: dict[str, Any]) -> Path:
    return _gravar_json(cfg.dados / "uc" / f"{cfg.schema}.json", snap)


def gravar_linhagem(cfg: nucleo.Config, lin: dict[str, Any]) -> Path:
    return _gravar_json(cfg.dados / "uc" / "linhagem.json", lin)


def gravar_extras(cfg: nucleo.Config, extras: dict[str, Any]) -> Path:
    return _gravar_json(cfg.dados / "uc" / "extras.json", extras)


def tabelas_unificadas(snap: dict[str, Any], extras: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """{fqn: {'nome','catalogo','schema','colunas','comentario','extra': bool}} do snapshot principal + extras."""
    saida: dict[str, dict[str, Any]] = {}
    cat, sch = snap.get("catalogo", ""), snap.get("schema", "")
    for nome, t in (snap.get("tabelas") or {}).items():
        saida[f"{cat}.{sch}.{nome}".lower()] = {"nome": nome, "catalogo": cat, "schema": sch, "colunas": t.get("colunas", []), "comentario": t.get("comentario", ""), "extra": False}
    for fqn, t in (extras or {}).items():
        saida[fqn.lower()] = {"nome": t.get("nome", fqn.split(".")[-1]), "catalogo": t.get("catalogo", ""), "schema": t.get("schema", ""), "colunas": t.get("colunas", []), "comentario": t.get("comentario", ""), "extra": True}
    return saida


def indice_colunas(snap: dict[str, Any], extras: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """SIGLA (maiuscula) -> [{'tabela','fqn','tipo','comentario','extra'}]. Uma sigla pode existir em varias tabelas."""
    idx: dict[str, list[dict[str, Any]]] = {}
    for fqn, t in tabelas_unificadas(snap, extras).items():
        for c in t["colunas"]:
            idx.setdefault(c["nome"].upper(), []).append({"tabela": t["nome"], "fqn": fqn, "tipo": c.get("tipo", ""), "comentario": c.get("comentario", ""), "extra": t["extra"]})
    return idx


def comentarios_colunas(snap: dict[str, Any]) -> dict[str, str]:
    saida: dict[str, str] = {}
    for t in (snap.get("tabelas") or {}).values():
        for c in t.get("colunas", []):
            if c.get("comentario"):
                saida.setdefault(c["nome"].upper(), c["comentario"])
    return saida


def descrever_campo(snap: dict[str, Any], lin: dict[str, Any], sigla: str, extras: dict[str, Any] | None = None) -> list[str]:
    idx = indice_colunas(snap, extras)
    ocorrencias = idx.get(sigla.upper(), [])
    if not ocorrencias:
        return [f"{sigla}: NAO encontrada em {snap.get('catalogo')}.{snap.get('schema')} nem nas tabelas incluidas (snapshot {snap.get('snapshot_id', '?')}). Se o pedido cita catalogo.schema.tabela, rode: python -m cdflw incluir-tabela <fqn>"]
    linhas = []
    rel = lin.get("relacoes") or {}
    for o in ocorrencias:
        onde = o["fqn"] if o["extra"] else o["tabela"]
        linhas.append(f"{sigla}: tabela {onde}, tipo {o['tipo'] or '?'}" + (f", comentario: {o['comentario']}" if o["comentario"] else "") + ("  [incluida sob demanda]" if o["extra"] else ""))
        chaves = [f"{o['tabela']}.{sigla}".lower(), f"{o['fqn']}.{sigla}".lower()]
        origens = []
        for k in chaves:
            origens += rel.get(k, [])
        for og in sorted(origens, key=lambda x: -x.get("n", 1))[:8]:
            linhas.append(f"    deriva de {og['origem']}")
    return linhas


def descrever_tabela(snap: dict[str, Any], nome: str, limite: int = 80, extras: dict[str, Any] | None = None) -> list[str]:
    todas = tabelas_unificadas(snap, extras)
    n = nome.lower().strip("`")
    t = todas.get(n)
    if not t:
        iguais = [f for f, v in todas.items() if v["nome"].lower() == n]
        if len(iguais) == 1:
            t = todas[iguais[0]]; n = iguais[0]
        elif len(iguais) > 1:
            return [f"'{nome}' existe em mais de um lugar: {', '.join(iguais)}. Use o nome qualificado."]
    if not t:
        candidatos = [f for f, v in todas.items() if n.split('.')[-1] in v["nome"].lower()]
        return [f"Tabela '{nome}' nao encontrada." + (f" Parecidas: {', '.join(candidatos[:10])}" if candidatos else "") + " Se for de outro schema, rode: python -m cdflw incluir-tabela catalogo.schema.tabela"]
    linhas = [f"{n}: {t.get('comentario') or '(sem comentario)'}" + ("  [incluida sob demanda]" if t["extra"] else ""), f"{len(t['colunas'])} colunas:"]
    for c in t["colunas"][:limite]:
        linhas.append(f"  {c['nome'].upper():<28} {c.get('tipo', ''):<18} {c.get('comentario', '')}".rstrip())
    if len(t["colunas"]) > limite:
        linhas.append(f"  ... e mais {len(t['colunas']) - limite}")
    return linhas


def resolver_fqn(cfg: nucleo.Config, nome: str, snap: dict[str, Any] | None = None, extras: dict[str, Any] | None = None) -> str:
    """Nome de tabela (sigla CadFlow, nome simples ou qualificado) -> nome qualificado, ou '' se nao resolver."""
    snap = snap if snap is not None else carregar_snapshot(cfg)
    extras = extras if extras is not None else carregar_extras(cfg)
    n = (nome or "").strip().strip("`")
    if n.count(".") == 2:
        return n.lower()
    n2 = cfg.mapa_uc.get(n.upper(), n).lower()
    todas = tabelas_unificadas(snap, extras)
    iguais = [f for f, v in todas.items() if v["nome"].lower() == n2]
    if len(iguais) == 1:
        return iguais[0]
    if snap.get("catalogo") and n2 in (snap.get("tabelas") or {}):
        return f"{snap['catalogo']}.{snap['schema']}.{n2}".lower()
    return ""


def encontrar_mascara(texto: str) -> bool:
    """Se o texto parece conter valor real (digitos ou letras) e nao so mascara (9/X)."""
    return bool(re.search(r"[0-8A-WYZa-wyz]", texto or ""))


# ==========================================================================================
# dados: Teste no dado: perfil de campo, teste de regra, exemplos, dominio e sobreposicao.
# ==========================================================================================




Resultado = dict[str, Any]


def _um_valor(linhas, i=0, j=0, padrao="0") -> str:
    try:
        return linhas[i][j]
    except (IndexError, TypeError):
        return padrao


def _total(cfg: nucleo.Config, fqn: str, **kw) -> tuple[int, list[str]]:
    linhas, erros, _ = executar_sql(cfg, f"SELECT count(*) FROM {fqn}", **kw)
    return int(float(_um_valor(linhas) or 0)), erros


def perfil(cfg: nucleo.Config, fqn: str, campo: str, mascarar: bool = True, **kw) -> Resultado:
    fqn = identificador(fqn); campo = identificador(campo)
    total, erros = _total(cfg, fqn, **kw)
    if erros and not total:
        return {"erro": "; ".join(erros)}
    fonte = fonte_amostrada(fqn, total, cfg.max_linhas_sem_amostra)
    sql = f"""SELECT count(*) AS n, count({campo}) AS nao_nulos, count(DISTINCT {campo}) AS distintos,
       min(length(CAST({campo} AS STRING))) AS tam_min, max(length(CAST({campo} AS STRING))) AS tam_max,
       sum(CASE WHEN CAST({campo} AS STRING) RLIKE '^[0-9]+$' THEN 1 ELSE 0 END) AS so_digitos,
       sum(CASE WHEN trim(CAST({campo} AS STRING)) = '' THEN 1 ELSE 0 END) AS vazios
FROM {fonte}"""
    linhas, erros2, via = executar_sql(cfg, sql, **kw)
    if not linhas:
        return {"erro": "; ".join(erros + erros2) or "sem resultado"}
    n, nao_nulos, distintos, tmin, tmax, so_dig, vazios = [float(x or 0) for x in linhas[0][:7]]
    top_sql = f"SELECT CAST({campo} AS STRING) AS v, count(*) AS n FROM {fonte} GROUP BY 1 ORDER BY 2 DESC LIMIT {cfg.max_valores_frequentes}"
    top, _e, _v = executar_sql(cfg, top_sql, **kw)
    frequentes = [{"valor": (mascarar_valor(l[0]) if mascarar else l[0]), "n": int(float(l[1] or 0))} for l in top if len(l) >= 2]
    pad_sql = f"SELECT regexp_replace(regexp_replace(CAST({campo} AS STRING), '[0-9]', '9'), '[A-Za-z]', 'X') AS p, count(*) AS n FROM {fonte} WHERE {campo} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 5"
    pads, _e, _v = executar_sql(cfg, pad_sql, **kw)
    return {
        "tabela": fqn, "campo": campo, "via": via, "amostrado": fonte != fqn, "total_tabela": total,
        "linhas_lidas": int(n), "nulos": int(n - nao_nulos), "taxa_nulos": round((n - nao_nulos) / n, 4) if n else 0.0,
        "vazios": int(vazios), "distintos": int(distintos), "tam_min": int(tmin), "tam_max": int(tmax),
        "so_digitos": int(so_dig), "taxa_so_digitos": round(so_dig / nao_nulos, 4) if nao_nulos else 0.0,
        "frequentes": frequentes, "padroes": [{"padrao": l[0], "n": int(float(l[1] or 0))} for l in pads if len(l) >= 2],
        "mascarado": mascarar, "erros": erros + erros2,
    }


def testar_predicado(cfg: nucleo.Config, fqn: str, predicado: str, **kw) -> Resultado:
    """Quantos registros o predicado (a regra) marcaria, e a taxa sobre o total."""
    fqn = identificador(fqn)
    pred = validar_predicado(predicado)
    total, erros = _total(cfg, fqn, **kw)
    sql = f"SELECT count(*) FROM {fqn} WHERE {pred}"
    validar_sql(sql)
    linhas, erros2, via = executar_sql(cfg, sql, **kw)
    if not linhas:
        return {"erro": "; ".join(erros + erros2) or "sem resultado", "sql": sql}
    marcados = int(float(_um_valor(linhas) or 0))
    return {"tabela": fqn, "predicado": pred, "sql": sql, "via": via, "total": total, "marcados": marcados,
            "taxa": round(marcados / total, 4) if total else 0.0, "testado_em": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "erros": erros + erros2}


def exemplos(cfg: nucleo.Config, fqn: str, campo: str, predicado: str = "", n: int = 5, mascarar: bool = True, **kw) -> Resultado:
    """Amostra de valores que atendem (e que nao atendem) o predicado."""
    fqn = identificador(fqn); campo = identificador(campo)
    n = max(1, min(n, cfg.max_valores_frequentes))
    saida: Resultado = {"tabela": fqn, "campo": campo, "mascarado": mascarar, "atendem": [], "nao_atendem": [], "erros": []}
    conds = [("atendem", predicado), ("nao_atendem", f"NOT ({predicado})")] if predicado else [("atendem", "")]
    for chave, cond in conds:
        if cond:
            cond = validar_predicado(cond)
        where = f"WHERE {campo} IS NOT NULL" + (f" AND ({cond})" if cond else "")
        sql = f"SELECT DISTINCT CAST({campo} AS STRING) FROM {fqn} {where} LIMIT {n}"
        validar_sql(sql)
        linhas, erros, _via = executar_sql(cfg, sql, **kw)
        saida[chave] = [(mascarar_valor(l[0]) if mascarar else l[0]) for l in linhas if l]
        saida["erros"] += erros
    return saida


def dominio(cfg: nucleo.Config, tabela_dominio: str, campo_codigo: str = "", n: int = 50, **kw) -> Resultado:
    """Confere que a tabela de dominio existe e lista os valores (primeira coluna, ou campo_codigo)."""
    fqn = resolver_fqn(cfg, tabela_dominio) or tabela_dominio
    fqn = identificador(fqn)
    col = identificador(campo_codigo) if campo_codigo else ""
    if not col:
        snap, extras = carregar_snapshot(cfg), carregar_extras(cfg)
        t = tabelas_unificadas(snap, extras).get(fqn.lower())
        if t and t["colunas"]:
            col = t["colunas"][0]["nome"]
    if not col:
        return {"erro": f"nao sei qual coluna de {fqn} guarda o codigo; informe --campo", "tabela": fqn}
    sql = f"SELECT DISTINCT CAST({col} AS STRING) FROM {fqn} ORDER BY 1 LIMIT {max(1, min(n, 500))}"
    linhas, erros, via = executar_sql(cfg, sql, **kw)
    return {"tabela": fqn, "campo": col, "valores": [l[0] for l in linhas if l], "via": via, "erros": erros}


def sobreposicao(cfg: nucleo.Config, fqn: str, predicado_novo: str, predicado_outro: str, **kw) -> Resultado:
    """Registros marcados pelos dois predicados: redundancia medida no dado."""
    fqn = identificador(fqn)
    a = validar_predicado(predicado_novo); b = validar_predicado(predicado_outro)
    sql = f"SELECT sum(CASE WHEN ({a}) THEN 1 ELSE 0 END), sum(CASE WHEN ({b}) THEN 1 ELSE 0 END), sum(CASE WHEN ({a}) AND ({b}) THEN 1 ELSE 0 END) FROM {fqn}"
    validar_sql(sql)
    linhas, erros, via = executar_sql(cfg, sql, **kw)
    if not linhas:
        return {"erro": "; ".join(erros) or "sem resultado"}
    na, nb, nab = [int(float(x or 0)) for x in linhas[0][:3]]
    return {"tabela": fqn, "novo": na, "outro": nb, "ambos": nab, "taxa_do_novo_ja_coberta": round(nab / na, 4) if na else 0.0, "via": via, "erros": erros}


def texto_perfil(p: Resultado) -> list[str]:
    if p.get("erro"):
        return [f"perfil: {p['erro']}"]
    l = [f"{p['tabela']}.{p['campo']}  (via {p['via']}{', amostra' if p['amostrado'] else ''}; total da tabela {p['total_tabela']:,})".replace(",", "."),
         f"  linhas lidas {p['linhas_lidas']:,} | nulos {p['nulos']:,} ({p['taxa_nulos']:.1%}) | vazios {p['vazios']:,} | distintos {p['distintos']:,}".replace(",", "."),
         f"  tamanho {p['tam_min']}..{p['tam_max']} | so digitos {p['taxa_so_digitos']:.1%}"]
    if p["padroes"]:
        l.append("  padroes mais comuns: " + ", ".join(f"{x['padrao']} ({x['n']})" for x in p["padroes"]))
    if p["frequentes"]:
        l.append("  valores mais frequentes" + (" (mascarados)" if p["mascarado"] else "") + ": " + ", ".join(f"{x['valor']} ({x['n']})" for x in p["frequentes"]))
    for e in p.get("erros", []):
        l.append(f"  aviso: {e}")
    return l


def texto_teste(t: Resultado) -> list[str]:
    if t.get("erro"):
        return [f"teste: {t['erro']}", f"  sql: {t.get('sql', '')}"]
    l = [f"{t['tabela']}: a regra marcaria {t['marcados']:,} de {t['total']:,} registros ({t['taxa']:.2%})  [via {t['via']}, {t['testado_em']}]".replace(",", "."),
         f"  predicado: {t['predicado']}"]
    if t["taxa"] > 0.5:
        l.append("  ATENCAO: mais da metade dos registros marcados. Ou a regra esta invertida, ou o pedido esta errado, ou o campo nao e o que se pensa.")
    elif t["marcados"] == 0:
        l.append("  nenhum registro marcado: a regra pode ser desnecessaria hoje, ou o predicado esta errado.")
    for e in t.get("erros", []):
        l.append(f"  aviso: {e}")
    return l
