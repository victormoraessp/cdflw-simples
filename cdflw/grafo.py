"""cdflw: o grafo das regras.

Construcao (regras, campos, tabelas, familia), analise de governanca (cadeias, impacto,
redundancia, hubs, cobertura, dimensoes, comunidades, GEXF) e a pagina grafo.html (offline).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from . import catalogo
from . import nucleo

# ==========================================================================================
# grafo: Grafo das regras: quem agrupa quem, quem chama quem, quem toca qual campo.
# ==========================================================================================




TIPO_POR_SUFIXO = {"RN": "Negócio", "RV": "Validação", "RE": "Enriquecimento", "RL": "Limpeza", "RR": "Retroalimentação", "RG": "Regra Geral"}


def _id(r: dict[str, Any]) -> str:
    return r.get("codigo") or r.get("codigo_comp") or f"nome:{nucleo.normalizar(r.get('nome', ''))[:60]}"


def construir(regras: list[dict[str, Any]], siglas_uc: set[str] | None = None) -> dict[str, Any]:
    nos: dict[str, dict[str, Any]] = {}
    arestas: list[dict[str, str]] = []
    por_codigo = {r["codigo"]: r for r in regras if r.get("codigo")}
    for r in regras:
        rid = _id(r)
        nos[rid] = {"tipo": "regra", "nome": r.get("nome", ""), "tipo_regra": r.get("tipo", ""),
                    "tabela_sigla": r.get("tabela_sigla", ""), "tipo_pessoa": r.get("tipo_pessoa", ""),
                    "status": r.get("status", ""), "criticidade": r.get("criticidade", "")}
        if r.get("rn"):
            arestas.append({"de": r["rn"], "para": rid, "rel": "agrupa"})
        for c in r.get("regras_encadeadas", []):
            # Limpeza/Enriquecimento citam a Validacao que segregou ("segregados pela regra X.RV.n"):
            # a seta e da validacao para o tratamento, nao o contrario
            if r.get("tipo") in ("Limpeza", "Enriquecimento", "Retroalimentação") and nucleo.decompor_codigo(c).get("tipo") == "RV":
                arestas.append({"de": c, "para": rid, "rel": "executa"})
            else:
                arestas.append({"de": rid, "para": c, "rel": "executa"})
        for cg in str(r.get("codigos_regra_geral", "")).replace(";", ",").split(","):
            cg = cg.strip().upper()
            if cg:
                arestas.append({"de": rid, "para": cg, "rel": "regra_geral"})
        for campo in r.get("campos", []):
            cid = f"campo:{campo.upper()}"
            nos.setdefault(cid, {"tipo": "campo", "sigla": campo.upper(), "existe_uc": (campo.upper() in siglas_uc) if siglas_uc else None})
            rel = "escreve" if r.get("tipo") in ("Enriquecimento", "Limpeza", "Retroalimentação") else "le"
            arestas.append({"de": rid, "para": cid, "rel": rel})
        if r.get("tabela_sigla"):
            tid = f"tabela:{r['tabela_sigla']}"
            nos.setdefault(tid, {"tipo": "tabela", "sigla": r["tabela_sigla"], "nome": r.get("tabela", "")})
            arestas.append({"de": rid, "para": tid, "rel": "pertence"})
    # sem arestas repetidas (a mesma relacao pode vir da acao da RV e do criterio da RL)
    vistas: set[tuple[str, str, str]] = set()
    arestas = [a for a in arestas if not ((a["de"], a["para"], a["rel"]) in vistas or vistas.add((a["de"], a["para"], a["rel"])))]
    # 'executa' para codigos que nao sao nos viram nos fantasmas, para a deteccao achar
    for a in arestas:
        if a["para"] not in nos and a["rel"] in ("executa", "agrupa", "regra_geral"):
            nos[a["para"]] = {"tipo": "regra", "nome": "", "fantasma": True, "tipo_regra": TIPO_POR_SUFIXO.get(nucleo.decompor_codigo(a["para"]).get("tipo", ""), "")}
        if a["de"] not in nos and a["rel"] == "agrupa":
            nos[a["de"]] = {"tipo": "regra", "nome": "", "fantasma": True, "tipo_regra": "Negócio"}
    return {"nos": nos, "arestas": arestas, "n_regras": len(por_codigo)}


def gravar(caminho: Path, g: dict[str, Any]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")


def carregar(caminho: Path) -> dict[str, Any]:
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {"nos": {}, "arestas": []}


def relacionadas(g: dict[str, Any], campos: list[str], tabela_sigla: str = "", tipo: str = "") -> list[dict[str, Any]]:
    """Regras existentes que tocam os mesmos campos ou a mesma tabela, com o motivo."""
    campos_u = {c.upper() for c in campos}
    motivos: dict[str, list[str]] = defaultdict(list)
    for a in g.get("arestas", []):
        if a["para"].startswith("campo:") and a["para"][6:] in campos_u:
            motivos[a["de"]].append(f"{a['rel']} {a['para'][6:]}")
    if tabela_sigla:
        for a in g.get("arestas", []):
            if a["rel"] == "pertence" and a["para"] == f"tabela:{tabela_sigla}" and a["de"] not in motivos:
                motivos[a["de"]].append(f"mesma tabela {tabela_sigla}")
    saida = []
    for rid, ms in motivos.items():
        no = g["nos"].get(rid, {})
        if no.get("fantasma"):
            continue
        peso = sum(2 if m.startswith("escreve") else 1 if not m.startswith("mesma") else 0.2 for m in ms)
        alerta = ""
        if tipo in ("Enriquecimento", "Limpeza", "Retroalimentação") and any(m.startswith("escreve") for m in ms):
            alerta = "COLISAO POSSIVEL: ja escreve no mesmo campo"
        elif tipo == "Validação" and no.get("tipo_regra") == "Validação" and any(m.startswith("le") for m in ms):
            alerta = "DUPLICATA POSSIVEL: ja valida o mesmo campo"
        saida.append({"codigo": rid, "nome": no.get("nome", ""), "tipo": no.get("tipo_regra", ""),
                      "tabela_sigla": no.get("tabela_sigla", ""), "motivos": ms, "peso": peso, "alerta": alerta})
    saida.sort(key=lambda x: -x["peso"])
    return saida


def detectar(g: dict[str, Any]) -> list[dict[str, str]]:
    """Problemas estruturais no conjunto de regras."""
    nos, arestas = g.get("nos", {}), g.get("arestas", [])
    achados: list[dict[str, str]] = []
    executa_de: dict[str, list[str]] = defaultdict(list)
    chamada_por: dict[str, list[str]] = defaultdict(list)
    escreve: dict[str, list[str]] = defaultdict(list)
    for a in arestas:
        if a["rel"] == "executa":
            executa_de[a["de"]].append(a["para"])
            chamada_por[a["para"]].append(a["de"])
        if a["rel"] == "escreve":
            escreve[a["para"]].append(a["de"])
    for rid, no in nos.items():
        if no.get("tipo") != "regra":
            continue
        if no.get("fantasma"):
            quem = [a["de"] for a in arestas if a["para"] == rid]
            achados.append({"tipo": "codigo_inexistente", "regra": rid, "detalhe": f"citada por {', '.join(quem)} mas nao existe na base"})
            continue
        t = no.get("tipo_regra", "")
        if t == "Validação" and not executa_de.get(rid):
            achados.append({"tipo": "validacao_sem_tratamento", "regra": rid, "detalhe": "valida e segrega, mas nao encadeia nenhuma Limpeza/Enriquecimento"})
        if t in ("Limpeza", "Enriquecimento") and not chamada_por.get(rid) and not any(a["de"] == rid and a["rel"] == "executa" for a in arestas):
            achados.append({"tipo": "tratamento_sem_validacao", "regra": rid, "detalhe": "nenhuma Validação encadeia esta regra"})
        for alvo in executa_de.get(rid, []):
            ta = nos.get(alvo, {}).get("tipo_regra", "")
            if t == "Validação" and ta and ta not in ("Limpeza", "Enriquecimento"):
                achados.append({"tipo": "encadeamento_tipo_errado", "regra": rid, "detalhe": f"Validação chamando {alvo} ({ta})"})
            d1, d2 = nucleo.decompor_codigo(rid), nucleo.decompor_codigo(alvo)
            if d1.get("prefixo") and d2.get("prefixo") and d1["prefixo"] != d2["prefixo"]:
                achados.append({"tipo": "encadeamento_outro_prefixo", "regra": rid, "detalhe": f"chama {alvo} de outra tabela"})
    for cid, quem in escreve.items():
        if len(quem) > 1:
            achados.append({"tipo": "colisao_escrita", "regra": ", ".join(sorted(quem)), "detalhe": f"mais de uma regra escreve em {cid[6:]}"})
    for cid, no in nos.items():
        if no.get("tipo") == "campo" and no.get("existe_uc") is False:
            quem = sorted({a["de"] for a in arestas if a["para"] == cid})
            achados.append({"tipo": "campo_fora_do_catalogo", "regra": ", ".join(quem), "detalhe": f"{no['sigla']} nao existe no snapshot do Unity Catalog"})
    return achados


def texto_detectados(achados: list[dict[str, str]]) -> str:
    if not achados:
        return "Nenhum problema estrutural encontrado."
    linhas = ["| Tipo | Regra(s) | Detalhe |", "|---|---|---|"]
    for a in achados:
        linhas.append("| " + " | ".join(nucleo.celula(x) for x in (a['tipo'], a['regra'], a['detalhe'])) + " |")
    return "\n".join(linhas)


# ==========================================================================================
# analise: Analise do grafo de regras: as visoes usuais de governanca de dados.
# ==========================================================================================




try:  # opcional
    import networkx as nx  # type: ignore
except Exception:  # noqa: BLE001
    nx = None

DIMENSOES_PADRAO: dict[str, dict[str, Any]] = {
    "completude": {"tipos": ["Enriquecimento"], "palavras": ["vazio", "preench", "nulo", "em branco", "ausente", "completa", "recupera"]},
    "validade": {"tipos": ["Validação"], "palavras": ["dominio", "formato", "digito", "tamanho", "padrao", "valido", "permitid", "faixa"]},
    "consistencia": {"tipos": ["Negócio", "Retroalimentação"], "palavras": ["consist", "coerente", "igual ao", "diverg", "equaliz", "entre"]},
    "unicidade": {"tipos": [], "palavras": ["duplic", "unico", "repetid", "mesmo cpf", "mesmo cnpj", "dedup"]},
    "acuracia": {"tipos": [], "palavras": ["receita federal", "rbrf", "bureau", "fonte externa", "fonte oficial", "confirmad", "quod"]},
    "atualidade": {"tipos": [], "palavras": ["desatualiz", "vigencia", "data de atualiz", "mais recente", "prazo", "expir"]},
    "integridade": {"tipos": ["Limpeza"], "palavras": ["apaga", "remove", "sanea", "termo proibid", "caractere"]},
}


# ---------------------------------------------------------------------------
# estruturas basicas
# ---------------------------------------------------------------------------
def _vizinhos(g: dict[str, Any]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(saida, entrada) por no, para todas as arestas."""
    out: dict[str, set[str]] = defaultdict(set)
    inn: dict[str, set[str]] = defaultdict(set)
    for a in g.get("arestas", []):
        out[a["de"]].add(a["para"])
        inn[a["para"]].add(a["de"])
    return out, inn


def _regras(g: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in g.get("nos", {}).items() if v.get("tipo") == "regra" and not v.get("fantasma")}


def _campos_da_regra(g: dict[str, Any]) -> dict[str, dict[str, set[str]]]:
    """regra -> {'le': {...}, 'escreve': {...}, 'todos': {...}} (siglas)."""
    saida: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"le": set(), "escreve": set(), "todos": set()})
    for a in g.get("arestas", []):
        if a["para"].startswith("campo:") and a["rel"] in ("le", "escreve", "condicionada_por"):
            s = a["para"][6:]
            saida[a["de"]]["todos"].add(s)
            saida[a["de"]]["escreve" if a["rel"] == "escreve" else "le"].add(s)
    return saida


def _bfs(adj: dict[str, set[str]], inicio: str, profundidade: int = 99) -> dict[str, int]:
    dist = {inicio: 0}
    fila = deque([inicio])
    while fila:
        n = fila.popleft()
        if dist[n] >= profundidade:
            continue
        for v in adj.get(n, ()):
            if v not in dist:
                dist[v] = dist[n] + 1
                fila.append(v)
    dist.pop(inicio, None)
    return dist


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# visoes
# ---------------------------------------------------------------------------
def cadeias(g: dict[str, Any]) -> dict[str, Any]:
    """RN -> filhas -> encadeamentos; completas, quebradas, ciclos e ordem de execucao."""
    nos = g.get("nos", {})
    out, _inn = _vizinhos(g)
    exec_out: dict[str, set[str]] = defaultdict(set)
    agrupa: dict[str, set[str]] = defaultdict(set)
    for a in g.get("arestas", []):
        if a["rel"] == "executa":
            exec_out[a["de"]].add(a["para"])
        elif a["rel"] == "agrupa":
            agrupa[a["de"]].add(a["para"])
    completas, quebradas = [], []
    for rid, no in _regras(g).items():
        if no.get("tipo_regra") != "Validação":
            continue
        alvos = exec_out.get(rid, set())
        tratadas = [t for t in alvos if nos.get(t, {}).get("tipo_regra") in ("Limpeza", "Enriquecimento") and not nos.get(t, {}).get("fantasma")]
        fantasmas = [t for t in alvos if nos.get(t, {}).get("fantasma")]
        item = {"validacao": rid, "nome": no.get("nome", ""), "tabela": no.get("tabela_sigla", ""), "trata": sorted(tratadas), "inexistentes": sorted(fantasmas)}
        (completas if tratadas and not fantasmas else quebradas).append(item)
    # ciclos (so arestas executa/agrupa), por DFS
    ciclos: list[list[str]] = []
    cor: dict[str, int] = {}
    pilha: list[str] = []

    def dfs(n: str):
        cor[n] = 1
        pilha.append(n)
        for v in exec_out.get(n, ()):
            if cor.get(v, 0) == 1:
                ciclos.append(pilha[pilha.index(v):] + [v])
            elif cor.get(v, 0) == 0:
                dfs(v)
        pilha.pop()
        cor[n] = 2

    for n in list(exec_out):
        if cor.get(n, 0) == 0:
            dfs(n)
    # ordem de execucao: RN primeiro, depois validacoes, depois tratamentos (Kahn sobre executa)
    indeg: dict[str, int] = defaultdict(int)
    for s, ts in exec_out.items():
        for t in ts:
            indeg[t] += 1
    regras = _regras(g)
    ordem_tipo = {"Negócio": 0, "Regra Geral": 0, "Validação": 1, "Enriquecimento": 2, "Limpeza": 3, "Retroalimentação": 4}
    prontos = sorted([r for r in regras if indeg[r] == 0], key=lambda r: (ordem_tipo.get(regras[r].get("tipo_regra", ""), 9), r))
    ordem: list[str] = []
    vistos: set[str] = set()
    while prontos:
        n = prontos.pop(0)
        if n in vistos:
            continue
        vistos.add(n)
        ordem.append(n)
        for v in sorted(exec_out.get(n, ())):
            indeg[v] -= 1
            if indeg[v] <= 0 and v in regras and v not in vistos:
                prontos.append(v)
        prontos.sort(key=lambda r: (ordem_tipo.get(regras[r].get("tipo_regra", ""), 9), r))
    por_rn = {rn: sorted(f) for rn, f in agrupa.items()}
    return {"completas": completas, "quebradas": quebradas, "ciclos": ciclos, "ordem_execucao": ordem, "por_regra_de_negocio": por_rn}


def impacto(g: dict[str, Any], alvo: str, profundidade: int = 4) -> dict[str, Any]:
    """Quem e afetado se `alvo` (campo:SIGLA, tabela:SIGLA ou regra) mudar: a jusante por le/escreve/executa/agrupa."""
    nos = g.get("nos", {})
    # grafo de influencia: regra escreve campo -> campo influencia quem le; regra executa outra; RN agrupa filhas
    adj: dict[str, set[str]] = defaultdict(set)
    for a in g.get("arestas", []):
        if a["rel"] == "escreve":
            adj[a["de"]].add(a["para"])          # regra -> campo
        elif a["rel"] in ("le", "condicionada_por"):
            adj[a["para"]].add(a["de"])          # campo -> regra que le
        elif a["rel"] in ("executa", "agrupa"):
            adj[a["de"]].add(a["para"])
        elif a["rel"] == "pertence":
            adj[a["para"]].add(a["de"])          # tabela -> regra
    chave = _resolver_no(g, alvo)
    if not chave:
        return {"alvo": alvo, "erro": "no nao encontrado"}
    dist = _bfs(adj, chave, profundidade)
    regras = sorted([(d, n) for n, d in dist.items() if nos.get(n, {}).get("tipo") == "regra"])
    campos = sorted([(d, n[6:]) for n, d in dist.items() if n.startswith("campo:")])
    return {"alvo": chave, "regras_afetadas": [{"regra": n, "distancia": d, "nome": nos[n].get("nome", ""), "tipo": nos[n].get("tipo_regra", "")} for d, n in regras],
            "campos_afetados": [{"campo": c, "distancia": d} for d, c in campos]}


def _resolver_no(g: dict[str, Any], alvo: str) -> str:
    nos = g.get("nos", {})
    a = alvo.strip()
    for cand in (a, a.upper(), f"campo:{a.upper()}", f"tabela:{a.upper()}"):
        if cand in nos:
            return cand
    # por nome de regra (substring)
    n = nucleo.normalizar(a)
    for k, v in nos.items():
        if v.get("tipo") == "regra" and n and n in nucleo.normalizar(v.get("nome", "")):
            return k
    return ""


def redundancias(g: dict[str, Any], limiar: float = 0.6) -> list[dict[str, Any]]:
    """Pares do mesmo tipo com campos parecidos; duplicata se as condicoes tambem se parecem, complemento se nao."""
    regras = _regras(g)
    cf = _campos_da_regra(g)
    ids = sorted(r for r in regras if cf[r]["todos"])
    pares = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if regras[a].get("tipo_regra") != regras[b].get("tipo_regra"):
                continue
            j = _jaccard(cf[a]["todos"], cf[b]["todos"])
            if j < limiar:
                continue
            cond_a = set(nucleo.normalizar(regras[a].get("condicao", "")).split())
            cond_b = set(nucleo.normalizar(regras[b].get("condicao", "")).split())
            jc = _jaccard(cond_a, cond_b) if (cond_a or cond_b) else None
            classe = "duplicata provavel" if (jc is None or jc >= 0.5) else "complemento provavel"
            pares.append({"a": a, "b": b, "tipo": regras[a].get("tipo_regra", ""), "jaccard_campos": round(j, 2), "jaccard_condicao": None if jc is None else round(jc, 2),
                          "campos_comuns": sorted(cf[a]["todos"] & cf[b]["todos"]), "classe": classe, "nome_a": regras[a].get("nome", ""), "nome_b": regras[b].get("nome", "")})
    pares.sort(key=lambda p: -p["jaccard_campos"])
    return pares


def projecao_regras(g: dict[str, Any], minimo: int = 2) -> list[dict[str, Any]]:
    cf = _campos_da_regra(g)
    ids = sorted(cf)
    saida = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            comum = cf[a]["todos"] & cf[b]["todos"]
            if len(comum) >= minimo:
                saida.append({"a": a, "b": b, "peso": len(comum), "campos": sorted(comum)})
    saida.sort(key=lambda p: -p["peso"])
    return saida


def projecao_tabelas(g: dict[str, Any]) -> list[dict[str, Any]]:
    """Tabelas ligadas por regras que citam campos de ambas (campo com tabela conhecida)."""
    nos = g.get("nos", {})
    tab_de_regra = {k: v.get("tabela_sigla", "") for k, v in _regras(g).items()}
    campos_tabelas: dict[str, set[str]] = defaultdict(set)
    for a in g.get("arestas", []):
        if a["para"].startswith("campo:") and tab_de_regra.get(a["de"]):
            campos_tabelas[a["para"]].add(tab_de_regra[a["de"]])
    pares: dict[tuple[str, str], set[str]] = defaultdict(set)
    for c, tabs in campos_tabelas.items():
        ts = sorted(tabs)
        for i, x in enumerate(ts):
            for y in ts[i + 1:]:
                pares[(x, y)].add(c[6:])
    return sorted([{"a": x, "b": y, "peso": len(cs), "campos": sorted(cs)} for (x, y), cs in pares.items()], key=lambda p: -p["peso"])


def hubs(g: dict[str, Any], top: int = 30) -> dict[str, Any]:
    out, inn = _vizinhos(g)
    campos = [k for k, v in g.get("nos", {}).items() if v.get("tipo") == "campo"]
    grau = {c: len(inn.get(c, ())) for c in campos}
    escritores = defaultdict(int)
    for a in g.get("arestas", []):
        if a["rel"] == "escreve":
            escritores[a["para"]] += 1
    inter: dict[str, float] = {}
    if nx is not None:
        G = nx.Graph()
        for a in g.get("arestas", []):
            if a["rel"] in ("le", "escreve", "condicionada_por", "executa", "agrupa"):
                G.add_edge(a["de"], a["para"])
        try:
            inter = nx.betweenness_centrality(G, normalized=True)
        except Exception:  # noqa: BLE001
            inter = {}
    lista = sorted(campos, key=lambda c: (-grau[c], -escritores[c], c))[:top]
    return {"campos": [{"campo": c[6:], "regras": grau[c], "escritores": escritores[c], "intermediacao": round(inter.get(c, 0.0), 4)} for c in lista],
            "com_intermediacao": nx is not None}


def comunidades(g: dict[str, Any]) -> dict[str, Any]:
    """Louvain (networkx) sobre regra-campo; sem networkx, componentes conexos."""
    regras = _regras(g)
    arestas = [(a["de"], a["para"]) for a in g.get("arestas", []) if a["rel"] in ("le", "escreve", "condicionada_por", "executa", "agrupa")]
    grupos: list[set[str]] = []
    metodo = "componentes"
    if nx is not None:
        G = nx.Graph(); G.add_edges_from(arestas)
        try:
            from networkx.algorithms.community import louvain_communities
            grupos = [set(c) for c in louvain_communities(G, seed=7)]
            metodo = "louvain"
        except Exception:  # noqa: BLE001
            grupos = [set(c) for c in nx.connected_components(G)]
    else:
        adj: dict[str, set[str]] = defaultdict(set)
        for a, b in arestas:
            adj[a].add(b); adj[b].add(a)
        vistos: set[str] = set()
        for n in list(adj):
            if n in vistos:
                continue
            comp = set(_bfs(adj, n)) | {n}
            vistos |= comp
            grupos.append(comp)
    saida = []
    for i, gr in enumerate(sorted(grupos, key=lambda s: -len(s))):
        rs = sorted(r for r in gr if r in regras)
        cs = sorted(c[6:] for c in gr if c.startswith("campo:"))
        if not rs:
            continue
        tabelas = sorted({regras[r].get("tabela_sigla", "") for r in rs} - {""})
        tem_rn = any(regras[r].get("tipo_regra") == "Negócio" for r in rs)
        saida.append({"id": i, "regras": rs, "campos": cs, "tabelas": tabelas, "tem_regra_de_negocio": tem_rn,
                      "sugestao": "" if tem_rn else "grupo sem Regra de Negocio cadastrada: candidato a RN implicita"})
    return {"metodo": metodo, "grupos": saida}


def cobertura(g: dict[str, Any], snap: dict[str, Any], extras: dict[str, Any], mapa_uc: dict[str, str]) -> dict[str, Any]:
    """Tabelas e campos do catalogo sem regra; regras e criticidade por tabela."""

    regras = _regras(g)
    cf = _campos_da_regra(g)
    campos_com_regra: set[str] = set()
    for r in regras:
        campos_com_regra |= cf[r]["todos"]
    por_tabela: dict[str, dict[str, Any]] = defaultdict(lambda: {"regras": 0, "por_tipo": defaultdict(int), "por_criticidade": defaultdict(int), "por_status": defaultdict(int)})
    for r, no in regras.items():
        t = no.get("tabela_sigla", "") or "(sem tabela)"
        por_tabela[t]["regras"] += 1
        por_tabela[t]["por_tipo"][no.get("tipo_regra", "?")] += 1
        por_tabela[t]["por_criticidade"][no.get("criticidade", "?") or "?"] += 1
        por_tabela[t]["por_status"][no.get("status", "?") or "?"] += 1
    inverso = {v.lower(): k for k, v in mapa_uc.items()}
    sem_regra_tabelas, campos_sem_regra = [], {}
    for fqn, t in catalogo.tabelas_unificadas(snap, extras).items():
        sigla = inverso.get(t["nome"].lower(), "")
        cols = {c["nome"].upper() for c in t["colunas"]}
        sem = sorted(cols - campos_com_regra)
        if not sigla:
            sem_regra_tabelas.append({"tabela": fqn, "colunas": len(cols)})
        else:
            campos_sem_regra[sigla] = {"tabela_uc": fqn, "sem_regra": sem, "total": len(cols), "cobertura": round(1 - len(sem) / len(cols), 2) if cols else 0.0}
    return {"por_tabela": {k: {"regras": v["regras"], "por_tipo": dict(v["por_tipo"]), "por_criticidade": dict(v["por_criticidade"]), "por_status": dict(v["por_status"])} for k, v in por_tabela.items()},
            "tabelas_do_catalogo_sem_regra": sem_regra_tabelas, "campos_sem_regra": campos_sem_regra}


def dimensoes(g: dict[str, Any], regras_texto: dict[str, str], dims: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Classifica cada regra nas dimensoes de qualidade (por tipo + palavras) e monta tabela x dimensao."""
    dims = dims or DIMENSOES_PADRAO
    regras = _regras(g)
    por_regra: dict[str, list[str]] = {}
    matriz: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r, no in regras.items():
        txt = nucleo.normalizar(regras_texto.get(r, "") + " " + no.get("nome", ""))
        achadas = []
        for d, spec in dims.items():
            if no.get("tipo_regra") in spec.get("tipos", []) or any(nucleo.normalizar(p) in txt for p in spec.get("palavras", [])):
                achadas.append(d)
        por_regra[r] = achadas or ["nao classificada"]
        for d in por_regra[r]:
            matriz[no.get("tabela_sigla", "") or "(sem tabela)"][d] += 1
    return {"dimensoes": list(dims), "por_regra": por_regra, "matriz": {t: dict(v) for t, v in matriz.items()}}


def explorar(g: dict[str, Any], met: dict[str, Any], alvo: str) -> list[str]:
    """Relatorio textual de um campo, tabela ou regra, juntando as visoes."""
    nos = g.get("nos", {})
    chave = _resolver_no(g, alvo)
    if not chave:
        return [f"'{alvo}' nao encontrado no grafo (campo, tabela ou regra)."]
    no = nos[chave]
    out, inn = _vizinhos(g)
    l = [f"== {chave}  ({no.get('tipo')})" + (f"  {no.get('nome', '')}" if no.get("nome") else "")]
    if no.get("tipo") == "regra":
        l.append(f"  tipo {no.get('tipo_regra')} | tabela {no.get('tabela_sigla')} | criticidade {no.get('criticidade')} | status {no.get('status')}")
        cf = _campos_da_regra(g).get(chave, {"le": set(), "escreve": set()})
        l.append(f"  le: {', '.join(sorted(cf['le'])) or '-'}")
        l.append(f"  escreve: {', '.join(sorted(cf['escreve'])) or '-'}")
        exec_ = [a["para"] for a in g["arestas"] if a["de"] == chave and a["rel"] == "executa"]
        chamada = [a["de"] for a in g["arestas"] if a["para"] == chave and a["rel"] == "executa"]
        rn = [a["de"] for a in g["arestas"] if a["para"] == chave and a["rel"] == "agrupa"]
        if rn:
            l.append(f"  regra de negocio: {', '.join(rn)}")
        if exec_:
            l.append(f"  executa: {', '.join(exec_)}")
        if chamada:
            l.append(f"  chamada por: {', '.join(chamada)}")
        l.append(f"  dimensoes: {', '.join(met.get('dimensoes', {}).get('por_regra', {}).get(chave, []))}")
        for p in met.get("redundancias", []):
            if chave in (p["a"], p["b"]):
                outro = p["b"] if p["a"] == chave else p["a"]
                l.append(f"  {p['classe']} com {outro} (campos {p['jaccard_campos']}): {', '.join(p['campos_comuns'])}")
    elif no.get("tipo") == "campo":
        regras = sorted(inn.get(chave, ()))
        l.append(f"  no catalogo: {'sim' if no.get('existe_uc') else 'NAO' if no.get('existe_uc') is False else 'nao conferido'}")
        l.append(f"  {len(regras)} regra(s) atrelada(s):")
        for r in regras:
            rel = [a["rel"] for a in g["arestas"] if a["de"] == r and a["para"] == chave]
            l.append(f"    {r} ({nos.get(r, {}).get('tipo_regra', '')}, {'/'.join(rel)}): {nos.get(r, {}).get('nome', '')[:70]}")
        h = next((x for x in met.get("hubs", {}).get("campos", []) if x["campo"] == chave[6:]), None)
        if h:
            l.append(f"  hub: {h['regras']} regras, {h['escritores']} escritor(es), intermediacao {h['intermediacao']}")
    elif no.get("tipo") == "tabela":
        regras = sorted(inn.get(chave, ()))
        cob = met.get("cobertura", {}).get("por_tabela", {}).get(no.get("sigla", ""), {})
        l.append(f"  {len(regras)} regra(s): por tipo {cob.get('por_tipo', {})} | por criticidade {cob.get('por_criticidade', {})}")
        csr = met.get("cobertura", {}).get("campos_sem_regra", {}).get(no.get("sigla", ""), {})
        if csr:
            l.append(f"  cobertura de campos: {csr.get('cobertura', 0):.0%} ({len(csr.get('sem_regra', []))} sem regra de {csr.get('total', 0)})")
        for t in met.get("projecao_tabelas", []):
            if no.get("sigla") in (t["a"], t["b"]):
                outra = t["b"] if t["a"] == no.get("sigla") else t["a"]
                l.append(f"  ligada a {outra} por {t['peso']} campo(s): {', '.join(t['campos'][:6])}")
    imp = impacto(g, chave, 3)
    if imp.get("regras_afetadas"):
        l.append(f"  impacto (ate 3 saltos): {len(imp['regras_afetadas'])} regra(s): " + ", ".join(f"{x['regra']}(d{x['distancia']})" for x in imp["regras_afetadas"][:12]))
    for c in met.get("comunidades", {}).get("grupos", []):
        if chave in c["regras"] or chave[6:] in c["campos"]:
            l.append(f"  comunidade #{c['id']}: {len(c['regras'])} regras, tabelas {', '.join(c['tabelas'])}" + (f"  <- {c['sugestao']}" if c["sugestao"] else ""))
            break
    return l


# ---------------------------------------------------------------------------
# orquestracao
# ---------------------------------------------------------------------------
def calcular(cfg: nucleo.Config, g: dict[str, Any], regras: list[dict[str, Any]], snap: dict[str, Any], extras: dict[str, Any]) -> dict[str, Any]:
    texto_por_regra = {}
    for r in regras:
        k = r.get("codigo") or f"nome:{nucleo.normalizar(r.get('nome', ''))[:60]}"
        texto_por_regra[k] = " ".join(str(r.get(c, "")) for c in ("descricao", "objetivo", "criterio_aplicacao", "logica_execucao", "resultado"))
        if k in g.get("nos", {}):
            g["nos"][k]["condicao"] = r.get("criterio_aplicacao", "")
    dims_cfg = cfg.bruto.get("analise", {}).get("dimensoes") or None
    met = {
        "gerado_em": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "com_networkx": nx is not None,
        "cadeias": cadeias(g),
        "redundancias": redundancias(g, cfg.limiar_redundancia),
        "projecao_regras": projecao_regras(g),
        "projecao_tabelas": projecao_tabelas(g),
        "hubs": hubs(g),
        "comunidades": comunidades(g),
        "cobertura": cobertura(g, snap, extras, cfg.mapa_uc),
        "dimensoes": dimensoes(g, texto_por_regra, dims_cfg),
    }
    return met


def gravar_metricas(cfg: nucleo.Config, met: dict[str, Any]) -> Path:
    p = cfg.dados / "metricas.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(met, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def carregar_metricas(cfg: nucleo.Config) -> dict[str, Any]:
    p = cfg.dados / "metricas.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _md_tabela(cab: list[str], linhas: list[list[Any]]) -> str:
    out = ["| " + " | ".join(cab) + " |", "|" + "---|" * len(cab)]
    for l in linhas:
        out.append("| " + " | ".join(nucleo.celula(x) for x in l) + " |")
    return "\n".join(out)


def gravar_visoes(cfg: nucleo.Config, met: dict[str, Any]) -> list[Path]:
    pasta = cfg.dados / "visoes"
    pasta.mkdir(parents=True, exist_ok=True)
    escritos = []
    c = met["cadeias"]
    txt = ["# Cadeias de execução", "", f"Completas: {len(c['completas'])} | Quebradas: {len(c['quebradas'])} | Ciclos: {len(c['ciclos'])}", "", "## Quebradas (validação sem tratamento válido)", "",
           _md_tabela(["Validação", "Tabela", "Nome", "Trata", "Inexistentes"], [[q["validacao"], q["tabela"], q["nome"][:60], ", ".join(q["trata"]) or "-", ", ".join(q["inexistentes"]) or "-"] for q in c["quebradas"]]),
           "", "## Ciclos", "", *([" -> ".join(x) for x in c["ciclos"]] or ["nenhum"]), "", "## Ordem de execução sugerida", "", *(f"{i + 1}. {r}" for i, r in enumerate(c["ordem_execucao"]))]
    escritos.append(_escrever(pasta / "cadeias.md", txt))
    r = met["redundancias"]
    txt = ["# Redundâncias prováveis", "", f"Limiar de similaridade de campos: {cfg.limiar_redundancia}", "",
           _md_tabela(["Classe", "A", "B", "Tipo", "Campos", "Cond.", "Em comum"], [[p["classe"], p["a"], p["b"], p["tipo"], p["jaccard_campos"], p["jaccard_condicao"] if p["jaccard_condicao"] is not None else "-", ", ".join(p["campos_comuns"][:6])] for p in r])]
    escritos.append(_escrever(pasta / "redundancias.md", txt))
    h = met["hubs"]
    txt = ["# Campos mais sensíveis (hubs)", "", "Quanto mais regras tocam um campo, mais cuidado ao mudar qualquer uma delas.", "",
           _md_tabela(["Campo", "Regras", "Escritores", "Intermediação"], [[x["campo"], x["regras"], x["escritores"], x["intermediacao"]] for x in h["campos"]])]
    escritos.append(_escrever(pasta / "hubs.md", txt))
    cb = met["cobertura"]
    txt = ["# Cobertura da governança", "", "## Regras por tabela", "",
           _md_tabela(["Tabela", "Regras", "Por tipo", "Por criticidade", "Por status"], [[t, v["regras"], v["por_tipo"], v["por_criticidade"], v["por_status"]] for t, v in sorted(cb["por_tabela"].items(), key=lambda kv: -kv[1]["regras"])]),
           "", "## Campos sem regra (tabelas mapeadas)", "",
           _md_tabela(["Sigla", "Tabela UC", "Cobertura", "Sem regra"], [[s, v["tabela_uc"], f"{v['cobertura']:.0%}", ", ".join(v["sem_regra"][:12]) + (" ..." if len(v["sem_regra"]) > 12 else "")] for s, v in cb["campos_sem_regra"].items()]),
           "", "## Tabelas do catálogo sem nenhuma regra", "", _md_tabela(["Tabela", "Colunas"], [[t["tabela"], t["colunas"]] for t in cb["tabelas_do_catalogo_sem_regra"]])]
    escritos.append(_escrever(pasta / "cobertura.md", txt))
    d = met["dimensoes"]
    dims = d["dimensoes"]
    txt = ["# Dimensões de qualidade por tabela", "", "Cada regra é classificada por tipo e palavras-chave. Uma regra pode cair em mais de uma dimensão.", "",
           _md_tabela(["Tabela"] + dims + ["não classificada"], [[t] + [v.get(x, 0) for x in dims] + [v.get("nao classificada", 0)] for t, v in sorted(d["matriz"].items())])]
    escritos.append(_escrever(pasta / "dimensoes.md", txt))
    cm = met["comunidades"]
    txt = [f"# Comunidades de regras ({cm['metodo']})", "", "Grupos de regras que compartilham campos. Grupo sem Regra de Negócio é candidato a RN implícita.", ""]
    for gr in cm["grupos"]:
        txt += [f"## Grupo {gr['id']} ({len(gr['regras'])} regras; tabelas {', '.join(gr['tabelas'])})" + (f"  **{gr['sugestao']}**" if gr["sugestao"] else ""), "", ", ".join(gr["regras"]), "", f"campos: {', '.join(gr['campos'][:20])}", ""]
    escritos.append(_escrever(pasta / "comunidades.md", txt))
    return escritos


def _escrever(p: Path, linhas: list[str]) -> Path:
    p.write_text("\n".join(linhas) + "\n", encoding="utf-8", newline="\n")
    return p


def exportar_gexf(g: dict[str, Any], met: dict[str, Any], caminho: Path) -> Path:
    """GEXF 1.2 (Gephi, Cytoscape) com atributos: tipo, tipo_regra, tabela, criticidade, status, comunidade, grau."""
    from xml.sax.saxutils import escape

    nos = g.get("nos", {})
    _out, inn = _vizinhos(g)
    com = {}
    for gr in met.get("comunidades", {}).get("grupos", []):
        for r in gr["regras"]:
            com[r] = gr["id"]
        for c in gr["campos"]:
            com[f"campo:{c}"] = gr["id"]
    attrs = [("tipo", "string"), ("tipo_regra", "string"), ("tabela", "string"), ("criticidade", "string"), ("status", "string"), ("comunidade", "integer"), ("grau_entrada", "integer"), ("nome", "string")]
    linhas = ['<?xml version="1.0" encoding="UTF-8"?>', '<gexf xmlns="http://www.gexf.net/1.2draft" version="1.2">', '<graph mode="static" defaultedgetype="directed">', '<attributes class="node">']
    for i, (a, t) in enumerate(attrs):
        linhas.append(f'<attribute id="{i}" title="{a}" type="{t}"/>')
    linhas += ["</attributes>", '<attributes class="edge"><attribute id="0" title="rel" type="string"/></attributes>', "<nodes>"]
    for nid, n in nos.items():
        rot = n.get("sigla") or nid
        vals = [n.get("tipo", ""), n.get("tipo_regra", ""), n.get("tabela_sigla") or n.get("sigla", "") if n.get("tipo") == "tabela" else n.get("tabela_sigla", ""), n.get("criticidade", ""), n.get("status", ""), com.get(nid, -1), len(inn.get(nid, ())), n.get("nome", "")]
        linhas.append(f'<node id="{escape(nid)}" label="{escape(rot)}"><attvalues>' + "".join(f'<attvalue for="{i}" value="{escape(str(v))}"/>' for i, v in enumerate(vals)) + "</attvalues></node>")
    linhas.append("</nodes><edges>")
    for i, a in enumerate(g.get("arestas", [])):
        linhas.append(f'<edge id="{i}" source="{escape(a["de"])}" target="{escape(a["para"])}"><attvalues><attvalue for="0" value="{escape(a["rel"])}"/></attvalues></edge>')
    linhas += ["</edges></graph></gexf>"]
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("\n".join(linhas), encoding="utf-8", newline="\n")
    return caminho


# ==========================================================================================
# grafo_html: Visualizacao do grafo de regras em um HTML unico, sem internet.
# ==========================================================================================



CORES = {
    "Negócio": "#f2c14e", "Validação": "#4e9af2", "Enriquecimento": "#5bc47c", "Limpeza": "#f26d4e",
    "Retroalimentação": "#b07cf2", "Regra Geral": "#8c8c8c", "campo": "#cfd8e3", "tabela": "#2f3e4e", "fantasma": "#e0b0b0",
}
PALETA_COM = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#46f0f0", "#f032e6", "#bcf60c", "#fabebe", "#008080", "#e6beff", "#9a6324", "#800000", "#aaffc3", "#808000", "#000075"]


def _dados(g: dict[str, Any], met: dict[str, Any]) -> dict[str, Any]:
    com: dict[str, int] = {}
    for gr in met.get("comunidades", {}).get("grupos", []):
        for r in gr["regras"]:
            com[r] = gr["id"]
        for c in gr["campos"]:
            com[f"campo:{c}"] = gr["id"]
    dims = met.get("dimensoes", {}).get("por_regra", {})
    hubs = {h["campo"]: h for h in met.get("hubs", {}).get("campos", [])}
    nos = []
    for nid, n in g.get("nos", {}).items():
        if n.get("tipo") == "regra":
            grupo = "fantasma" if n.get("fantasma") else (n.get("tipo_regra") or "Regra Geral")
            nos.append({"id": nid, "rotulo": nid if not nid.startswith("nome:") else n.get("nome", nid)[:40], "grupo": grupo, "nome": n.get("nome", ""),
                        "tabela": n.get("tabela_sigla", ""), "status": n.get("status", ""), "criticidade": n.get("criticidade", ""), "pessoa": n.get("tipo_pessoa", ""),
                        "comunidade": com.get(nid, -1), "dimensoes": dims.get(nid, [])})
        elif n.get("tipo") == "campo":
            h = hubs.get(n.get("sigla", ""), {})
            nos.append({"id": nid, "rotulo": n.get("sigla", nid[6:]), "grupo": "campo", "nome": "", "tabela": "", "existe_uc": n.get("existe_uc"), "comunidade": com.get(nid, -1),
                        "hub": h.get("regras", 0), "intermediacao": h.get("intermediacao", 0)})
        elif n.get("tipo") == "tabela":
            nos.append({"id": nid, "rotulo": n.get("sigla", nid[7:]), "grupo": "tabela", "nome": n.get("nome", ""), "tabela": n.get("sigla", ""), "comunidade": -1})
    tabela_de_regra = {n["id"]: n["tabela"] for n in nos if n["grupo"] not in ("campo", "tabela")}
    tabela_de_campo: dict[str, set[str]] = {}
    for a in g.get("arestas", []):
        if a["para"].startswith("campo:"):
            tabela_de_campo.setdefault(a["para"], set()).add(tabela_de_regra.get(a["de"], ""))
    for n in nos:
        if n["grupo"] == "campo":
            n["tabelas"] = sorted(t for t in tabela_de_campo.get(n["id"], set()) if t)
    red = [{"a": p["a"], "b": p["b"], "classe": p["classe"], "j": p["jaccard_campos"]} for p in met.get("redundancias", [])]
    quebradas = {q["validacao"] for q in met.get("cadeias", {}).get("quebradas", [])}
    return {"nos": nos, "arestas": [{"de": a["de"], "para": a["para"], "rel": a["rel"]} for a in g.get("arestas", [])], "cores": CORES, "paleta": PALETA_COM,
            "redundancias": red, "quebradas": sorted(quebradas), "dimensoes": met.get("dimensoes", {}).get("dimensoes", []),
            "cobertura": met.get("cobertura", {}).get("por_tabela", {}), "gerado_em": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "com_metricas": bool(met)}


_HTML = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>cdflw: grafo de regras</title>
<style>
 body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#f6f7f9;color:#222;display:flex;height:100vh;overflow:hidden}
 #painel{width:380px;padding:12px;box-sizing:border-box;background:#fff;border-right:1px solid #ddd;overflow:auto;font-size:13px}
 #painel h1{font-size:16px;margin:0 0 6px}
 #painel label{display:block;margin:6px 0 2px;color:#555}
 #painel input,#painel select{width:100%;box-sizing:border-box;padding:4px}
 .linha{display:flex;gap:6px}.linha>*{flex:1}
 #legenda span{display:inline-block;margin:2px 6px 2px 0}#legenda i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:3px;vertical-align:middle}
 #detalhe{margin-top:10px;padding:8px;background:#f1f4f8;border-radius:4px;min-height:60px;font-size:12px;line-height:1.4}
 #detalhe b{color:#1a4d8f}#detalhe h3{margin:8px 0 2px;font-size:12px;color:#444;text-transform:uppercase;letter-spacing:.5px}
 #detalhe a{color:#1a4d8f;cursor:pointer;text-decoration:underline}
 .alerta{color:#b00020;font-weight:bold}
 #sug{position:absolute;background:#fff;border:1px solid #bbb;max-height:200px;overflow:auto;z-index:5;width:340px;display:none;font-size:12px}
 #sug div{padding:3px 6px;cursor:pointer}#sug div:hover{background:#e8eef7}
 canvas{flex:1;cursor:grab}
 .dica{color:#777;font-size:11px}
 button{padding:4px 8px;font-size:12px}
</style></head><body>
<div id="painel">
 <h1>cdflw: grafo de regras</h1>
 <div class="dica">__GERADO__. Arraste para mover, roda do mouse para zoom, clique num nó. Legenda das linhas: laranja = executa, amarelo = agrupa (RN), verde = escreve, cinza = lê, vermelho tracejado = redundância.</div>
 <label>Procurar (campo, tabela, código, nome)</label><input id="busca" placeholder="ex.: ICT.RV ou CMPO_DDD ou apelido" autocomplete="off"><div id="sug"></div>
 <div class="linha"><div><label>Tabela</label><select id="tabela"><option value="">todas</option></select></div>
 <div><label>Tipo</label><select id="tipo"><option value="">todos</option></select></div></div>
 <div class="linha"><div><label>Status</label><select id="status"><option value="">todos</option></select></div>
 <div><label>Criticidade</label><select id="crit"><option value="">todas</option></select></div></div>
 <div class="linha"><div><label>Dimensão</label><select id="dim"><option value="">todas</option></select></div>
 <div><label>Cor por</label><select id="corpor"><option value="tipo">tipo</option><option value="comunidade">comunidade</option></select></div></div>
 <div class="linha"><div><label>Vizinhança (saltos a partir da busca)</label><select id="saltos"><option value="0">só os achados</option><option value="1" selected>1</option><option value="2">2</option><option value="3">3</option></select></div>
 <div><label>&nbsp;</label><label><input type="checkbox" id="campos" checked style="width:auto"> mostrar campos</label><label><input type="checkbox" id="red" style="width:auto"> linhas de redundância</label></div></div>
 <div class="linha"><button id="btnPng">Exportar PNG</button><button id="btnReset">Limpar filtros</button><button id="btnQueb">Só cadeias quebradas</button></div>
 <div id="legenda"></div>
 <div id="stats" class="dica"></div>
 <div id="detalhe">Clique em um nó ou procure.</div>
</div>
<canvas id="c"></canvas>
<script>
const D = __DADOS__;
const cv = document.getElementById('c'), ctx = cv.getContext('2d');
const nosPorId = {}; D.nos.forEach(n => { nosPorId[n.id] = n; n.x = Math.random()*900; n.y = Math.random()*700; n.vx = 0; n.vy = 0; });
const viz = {}; D.arestas.forEach(a => { (viz[a.de] = viz[a.de] || new Set()).add(a.para); (viz[a.para] = viz[a.para] || new Set()).add(a.de); });
const redPorNo = {}; D.redundancias.forEach(p => { (redPorNo[p.a] = redPorNo[p.a] || []).push(p); (redPorNo[p.b] = redPorNo[p.b] || []).push(p); });
let visiveis = new Set(), arestasVis = [], escala = 1, ox = 0, oy = 0, arrasto = null, noArrasto = null, selecionado = null, quente = 300, achados = new Set();
const $ = id => document.getElementById(id);
function opcoes(sel, vals) { [...new Set(vals)].filter(Boolean).sort().forEach(v => { const o = document.createElement('option'); o.value = v; o.textContent = v; sel.appendChild(o); }); }
const regras = D.nos.filter(n => n.grupo !== 'campo' && n.grupo !== 'tabela');
opcoes($('tabela'), regras.map(n => n.tabela)); opcoes($('tipo'), regras.map(n => n.grupo)); opcoes($('status'), regras.map(n => n.status)); opcoes($('crit'), regras.map(n => n.criticidade)); opcoes($('dim'), D.dimensoes);
Object.entries(D.cores).forEach(([k, c]) => { $('legenda').innerHTML += `<span><i style="background:${c}"></i>${k}</span>`; });
function cor(n) { if ($('corpor').value === 'comunidade' && n.comunidade >= 0) return D.paleta[n.comunidade % D.paleta.length]; return D.cores[n.grupo] || '#999'; }
function passaFiltro(n) {
  const t = $('tabela').value, tp = $('tipo').value, st = $('status').value, cr = $('crit').value, dm = $('dim').value;
  if (n.grupo === 'campo') { if (!$('campos').checked) return false; if (t && !(n.tabelas || []).includes(t)) return false; return !(tp || st || cr || dm); }
  if (n.grupo === 'tabela') return (!t || n.tabela === t) && !(tp || st || cr || dm);
  return (!t || n.tabela === t) && (!tp || n.grupo === tp) && (!st || n.status === st) && (!cr || n.criticidade === cr) && (!dm || (n.dimensoes || []).includes(dm));
}
function filtrar() {
  const q = $('busca').value.trim().toUpperCase(), saltos = +$('saltos').value;
  let ids = new Set(D.nos.filter(passaFiltro).map(n => n.id));
  achados = new Set();
  if (q) {
    const hit = new Set(D.nos.filter(n => (n.id + ' ' + n.rotulo + ' ' + n.nome).toUpperCase().includes(q)).map(n => n.id));
    achados = hit;
    let fronteira = new Set(hit), todos = new Set(hit);
    for (let s = 0; s < saltos; s++) { const prox = new Set(); fronteira.forEach(id => (viz[id] || []).forEach(v => { if (!todos.has(v)) { todos.add(v); prox.add(v); } })); fronteira = prox; }
    ids = new Set([...todos].filter(id => { const n = nosPorId[id]; return n.grupo === 'campo' ? $('campos').checked : true; }));
  }
  visiveis = ids;
  arestasVis = D.arestas.filter(a => ids.has(a.de) && ids.has(a.para));
  $('stats').textContent = `${ids.size} nós, ${arestasVis.length} relações visíveis (de ${D.nos.length} / ${D.arestas.length})` + (D.com_metricas ? '' : ' | sem métricas: rode /atualizar');
  quente = 300;
}
function passo() {
  const ns = D.nos.filter(n => visiveis.has(n.id)); if (!ns.length) return;
  const k = 0.02, rep = 1800;
  for (let i = 0; i < ns.length; i++) { const a = ns[i]; for (let j = i + 1; j < ns.length; j++) { const b = ns[j]; let dx = a.x - b.x, dy = a.y - b.y, d2 = dx*dx + dy*dy + 0.01; if (d2 > 90000) continue; const f = rep / d2; dx *= f; dy *= f; a.vx += dx; a.vy += dy; b.vx -= dx; b.vy -= dy; } }
  arestasVis.forEach(e => { const a = nosPorId[e.de], b = nosPorId[e.para]; const dx = b.x - a.x, dy = b.y - a.y; a.vx += dx * k; a.vy += dy * k; b.vx -= dx * k; b.vy -= dy * k; });
  const cx = ns.reduce((s, n) => s + n.x, 0) / ns.length, cy = ns.reduce((s, n) => s + n.y, 0) / ns.length;
  ns.forEach(n => { if (n === noArrasto) return; n.vx += (450 - cx) * 0.001; n.vy += (350 - cy) * 0.001; n.vx *= 0.6; n.vy *= 0.6; n.x += Math.max(-15, Math.min(15, n.vx)); n.y += Math.max(-15, Math.min(15, n.vy)); });
}
function desenhar() {
  cv.width = cv.clientWidth; cv.height = cv.clientHeight; ctx.fillStyle = '#f6f7f9'; ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.save(); ctx.translate(ox, oy); ctx.scale(escala, escala);
  arestasVis.forEach(e => { const a = nosPorId[e.de], b = nosPorId[e.para]; ctx.strokeStyle = e.rel === 'executa' ? '#e05a2b' : e.rel === 'agrupa' ? '#c9a227' : e.rel === 'escreve' ? '#2b7a3d' : '#bbb'; ctx.lineWidth = e.rel === 'pertence' ? 0.4 : (e.rel === 'executa' || e.rel === 'agrupa') ? 1.6 : 1; ctx.setLineDash([]); ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); });
  if ($('red').checked) D.redundancias.forEach(p => { if (visiveis.has(p.a) && visiveis.has(p.b)) { const a = nosPorId[p.a], b = nosPorId[p.b]; ctx.strokeStyle = '#d00'; ctx.setLineDash([4, 3]); ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); } });
  ctx.setLineDash([]);
  D.nos.forEach(n => { if (!visiveis.has(n.id)) return; const r = n.grupo === 'campo' ? (n.hub ? 4 + Math.min(6, n.hub / 2) : 4) : n.grupo === 'tabela' ? 9 : 7; ctx.fillStyle = cor(n); ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 7); ctx.fill();
    if (D.quebradas.includes(n.id)) { ctx.strokeStyle = '#d00'; ctx.lineWidth = 2; ctx.stroke(); }
    if (achados.has(n.id)) { ctx.strokeStyle = '#000'; ctx.lineWidth = 2.5; ctx.stroke(); }
    if (n === selecionado) { ctx.strokeStyle = '#1a4d8f'; ctx.lineWidth = 3; ctx.stroke(); }
    if (n.grupo !== 'campo' || escala > 1.3 || visiveis.size < 80) { ctx.fillStyle = '#333'; ctx.font = `${n.grupo === 'tabela' ? 12 : 10}px sans-serif`; ctx.fillText(n.rotulo, n.x + r + 2, n.y + 3); } });
  ctx.restore();
}
function loop() { if (quente > 0) { passo(); quente--; } desenhar(); requestAnimationFrame(loop); }
function noEm(px, py) { const x = (px - ox) / escala, y = (py - oy) / escala; let m = null, md = 120; D.nos.forEach(n => { if (!visiveis.has(n.id)) return; const d = (n.x - x) ** 2 + (n.y - y) ** 2; if (d < md) { md = d; m = n; } }); return m; }
cv.addEventListener('mousedown', e => { const n = noEm(e.offsetX, e.offsetY); if (n) noArrasto = n; else arrasto = { x: e.offsetX - ox, y: e.offsetY - oy }; });
cv.addEventListener('mousemove', e => { if (noArrasto) { noArrasto.x = (e.offsetX - ox) / escala; noArrasto.y = (e.offsetY - oy) / escala; quente = Math.max(quente, 30); } else if (arrasto) { ox = e.offsetX - arrasto.x; oy = e.offsetY - arrasto.y; } });
cv.addEventListener('mouseup', () => { if (noArrasto) selecionar(noArrasto); noArrasto = null; arrasto = null; });
cv.addEventListener('wheel', e => { e.preventDefault(); const f = e.deltaY < 0 ? 1.1 : 0.9; ox = e.offsetX - (e.offsetX - ox) * f; oy = e.offsetY - (e.offsetY - oy) * f; escala *= f; }, { passive: false });
function bfs(id, prof, dir) { const dist = {}; dist[id] = 0; const fila = [id]; while (fila.length) { const n = fila.shift(); if (dist[n] >= prof) continue; D.arestas.forEach(a => { let v = null; if (dir === 'jusante') { if (a.de === n && (a.rel === 'escreve' || a.rel === 'executa' || a.rel === 'agrupa')) v = a.para; if (a.para === n && (a.rel === 'le' || a.rel === 'condicionada_por') && n.startsWith('campo:')) v = a.de; if (a.para === n && a.rel === 'pertence') v = a.de; } if (v && !(v in dist)) { dist[v] = dist[n] + 1; fila.push(v); } }); } delete dist[id]; return dist; }
function link(id) { return `<a onclick="irPara('${id.replace(/'/g, "\\'")}')">${id}</a>`; }
function irPara(id) { const n = nosPorId[id]; if (!n) return; $('busca').value = n.grupo === 'campo' ? n.rotulo : id; filtrar(); selecionar(n); }
function selecionar(n) {
  selecionado = n; const d = $('detalhe'); let h = `<b>${n.id}</b> <span class="dica">${n.grupo}</span>`;
  if (n.nome) h += `<br>${n.nome}`;
  if (n.grupo !== 'campo' && n.grupo !== 'tabela') {
    h += `<br>tabela ${n.tabela || '-'} · criticidade ${n.criticidade || '-'} · ${n.pessoa || ''} · status ${n.status || '-'}`;
    if (n.dimensoes && n.dimensoes.length) h += `<br>dimensões: ${n.dimensoes.join(', ')}`;
    if (D.quebradas.includes(n.id)) h += `<br><span class="alerta">cadeia quebrada: validação sem tratamento válido</span>`;
    const le = D.arestas.filter(a => a.de === n.id && (a.rel === 'le' || a.rel === 'condicionada_por')).map(a => link(a.para));
    const esc = D.arestas.filter(a => a.de === n.id && a.rel === 'escreve').map(a => link(a.para));
    const ex = D.arestas.filter(a => a.de === n.id && a.rel === 'executa').map(a => link(a.para));
    const por = D.arestas.filter(a => a.para === n.id && a.rel === 'executa').map(a => link(a.de));
    const rn = D.arestas.filter(a => a.para === n.id && a.rel === 'agrupa').map(a => link(a.de));
    const filhas = D.arestas.filter(a => a.de === n.id && a.rel === 'agrupa').map(a => link(a.para));
    h += `<h3>Campos</h3>lê: ${le.join(', ') || '-'}<br>escreve: ${esc.join(', ') || '-'}`;
    h += `<h3>Cadeia</h3>${rn.length ? 'regra de negócio: ' + rn.join(', ') + '<br>' : ''}${filhas.length ? 'agrupa: ' + filhas.join(', ') + '<br>' : ''}executa: ${ex.join(', ') || '-'}<br>chamada por: ${por.join(', ') || '-'}`;
    const rd = redPorNo[n.id] || []; if (rd.length) h += `<h3>Redundância</h3>` + rd.map(p => `${p.classe} com ${link(p.a === n.id ? p.b : p.a)} (${p.j})`).join('<br>');
  } else if (n.grupo === 'campo') {
    h += `<br>no catálogo: ${n.existe_uc === null || n.existe_uc === undefined ? 'não conferido' : n.existe_uc ? 'sim' : '<span class="alerta">NÃO</span>'} · tabelas: ${(n.tabelas || []).join(', ') || '-'}`;
    if (n.hub) h += `<br>hub: ${n.hub} regras, intermediação ${n.intermediacao}`;
    const rs = D.arestas.filter(a => a.para === n.id).map(a => `${link(a.de)} <span class="dica">${a.rel}</span>`);
    h += `<h3>Regras atreladas (${rs.length})</h3>${rs.join('<br>') || '-'}`;
  } else {
    const rs = D.arestas.filter(a => a.para === n.id && a.rel === 'pertence').map(a => link(a.de));
    const cb = D.cobertura[n.tabela] || {};
    h += `<h3>Regras (${rs.length})</h3>${rs.join(', ') || '-'}`;
    if (cb.por_tipo) h += `<h3>Cobertura</h3>por tipo: ${JSON.stringify(cb.por_tipo)}<br>por criticidade: ${JSON.stringify(cb.por_criticidade)}<br>por status: ${JSON.stringify(cb.por_status)}`;
  }
  const imp = bfs(n.id, 3, 'jusante'); const impR = Object.entries(imp).filter(([k]) => nosPorId[k] && nosPorId[k].grupo !== 'campo' && nosPorId[k].grupo !== 'tabela').sort((a, b) => a[1] - b[1]);
  if (impR.length) h += `<h3>Impacto a jusante (3 saltos): ${impR.length} regras</h3>` + impR.slice(0, 15).map(([k, dd]) => `${link(k)} <span class="dica">d${dd}</span>`).join(', ');
  if (n.comunidade >= 0) h += `<h3>Comunidade</h3>#${n.comunidade}`;
  d.innerHTML = h;
}
const sug = $('sug'); $('busca').addEventListener('input', () => { filtrar(); const q = $('busca').value.trim().toUpperCase(); if (!q) { sug.style.display = 'none'; return; } const its = D.nos.filter(n => (n.id + ' ' + n.rotulo + ' ' + n.nome).toUpperCase().includes(q)).slice(0, 12); sug.innerHTML = its.map(n => `<div onclick="irPara('${n.id.replace(/'/g, "\\'")}');document.getElementById('sug').style.display='none'">${n.grupo === 'campo' ? n.rotulo : n.id} <span class="dica">${n.grupo}${n.nome ? ' · ' + n.nome.slice(0, 40) : ''}</span></div>`).join(''); sug.style.display = its.length ? 'block' : 'none'; });
$('busca').addEventListener('blur', () => setTimeout(() => sug.style.display = 'none', 200));
['tabela', 'tipo', 'status', 'crit', 'dim', 'campos', 'saltos', 'red'].forEach(id => $(id).addEventListener('input', filtrar));
$('corpor').addEventListener('input', () => {});
$('btnReset').onclick = () => { ['tabela', 'tipo', 'status', 'crit', 'dim'].forEach(id => $(id).value = ''); $('busca').value = ''; filtrar(); };
$('btnQueb').onclick = () => { $('busca').value = ''; filtrar(); visiveis = new Set(); D.quebradas.forEach(q => { visiveis.add(q); (viz[q] || []).forEach(v => visiveis.add(v)); }); arestasVis = D.arestas.filter(a => visiveis.has(a.de) && visiveis.has(a.para)); $('stats').textContent = `${D.quebradas.length} validações sem tratamento válido`; quente = 300; };
$('btnPng').onclick = () => { const a = document.createElement('a'); a.download = 'grafo_regras.png'; a.href = cv.toDataURL('image/png'); a.click(); };
filtrar(); loop();
</script></body></html>
"""


def gerar(g: dict[str, Any], caminho: Path, met: dict[str, Any] | None = None) -> Path:
    dados = json.dumps(_dados(g, met or {}), ensure_ascii=False).replace("</", "<\\/")
    html = _HTML.replace("__DADOS__", dados).replace("__GERADO__", f"Gerado em {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(html, encoding="utf-8", newline="\n")
    return caminho
