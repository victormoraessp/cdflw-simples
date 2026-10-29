"""cdflw: linha de comando e trilha da conversa.

    python -m cdflw <comando> ...   (a partir da raiz do repositorio)

Todo comando espelha a saida em saida/_ultimo_comando.txt e, com a trilha ligada, vira um evento
em saida/_trilha.jsonl (+ _trilha.html ao vivo).
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import html
import json
import sys
from pathlib import Path
from typing import Any

from . import catalogo
from . import grafo
from . import nucleo

# ==========================================================================================
# trilha: Trilha da conversa: o caminho observavel do agente ate o resultado.
# ==========================================================================================




CAMPOS_FICHA = ["codigo", "codigo_comp", "rn", "nome", "tipo", "criticidade", "tabela", "tabela_sigla", "tipo_pessoa", "descricao", "objetivo",
                "criterio_aplicacao", "logica_execucao", "resultado", "exemplo", "acao_dado_valido", "acao_dado_invalido", "observacao", "pontos_atencao", "familia", "sql_teste", "tabela_uc", "teste_no_dado"]

TIPOS = {
    "comando": "#4e9af2", "leu": "#b07cf2", "conclusao": "#5bc47c", "pergunta": "#f2c14e", "resposta": "#f2c14e",
    "ficha": "#8c8c8c", "gravou": "#2b7a3d", "erro": "#f26d4e", "inicio": "#2f3e4e", "nota": "#cfd8e3",
}


def ativa(cfg: nucleo.Config) -> bool:
    return bool(cfg.bruto.get("trilha", {}).get("ativa", True))


def _arquivo(cfg: nucleo.Config) -> Path:
    return cfg.saida / "_trilha.jsonl"


def _html(cfg: nucleo.Config) -> Path:
    return cfg.saida / "_trilha.html"


def ler(cfg: nucleo.Config) -> list[dict[str, Any]]:
    p = _arquivo(cfg)
    if not p.exists():
        return []
    out = []
    for l in p.read_text(encoding="utf-8").splitlines():
        if l.strip():
            try:
                out.append(json.loads(l))
            except json.JSONDecodeError:
                continue
    return out


def registrar(cfg: nucleo.Config, tipo: str, titulo: str, detalhe: str = "", extra: dict[str, Any] | None = None, regerar: bool = True) -> None:
    """Acrescenta um evento e regera o HTML. Nunca levanta excecao: a trilha nao pode quebrar o comando."""
    try:
        if not ativa(cfg):
            return
        p = _arquivo(cfg)
        p.parent.mkdir(parents=True, exist_ok=True)
        ev = {"t": dt.datetime.now().strftime("%H:%M:%S"), "tipo": tipo, "titulo": titulo[:200], "detalhe": (detalhe or "")[:6000]}
        if extra:
            ev.update(extra)
        with p.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        if regerar:
            gerar_html(cfg)
    except Exception:  # noqa: BLE001
        pass


def nova(cfg: nucleo.Config, motivo: str = "") -> None:
    p = _arquivo(cfg)
    if p.exists():
        p.unlink()
    registrar(cfg, "inicio", "nova conversa" + (f": {motivo}" if motivo else ""))


def limpar(cfg: nucleo.Config) -> None:
    for p in (_arquivo(cfg), _html(cfg)):
        if p.exists():
            p.unlink()


def registrar_ficha(cfg: nucleo.Config, ficha: dict[str, Any], origem: str) -> None:
    """Guarda a versao da ficha e o diff contra a anterior."""
    atual = {k: str(ficha.get(k, "") or "") for k in CAMPOS_FICHA}
    anterior: dict[str, str] = {}
    for ev in reversed(ler(cfg)):
        if ev.get("tipo") == "ficha" and ev.get("ficha"):
            anterior = ev["ficha"]
            break
    mudou = [k for k in CAMPOS_FICHA if atual.get(k, "") != anterior.get(k, "")]
    if not mudou and anterior:
        return
    linhas = []
    for k in mudou:
        a, b = anterior.get(k, ""), atual.get(k, "")
        if not a:
            linhas.append(f"+ {k}: {b}")
        elif not b:
            linhas.append(f"- {k}: {a}")
        else:
            d = "\n".join(difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0))
            linhas.append(f"~ {k}:\n{d}")
    registrar(cfg, "ficha", f"ficha v{sum(1 for e in ler(cfg) if e.get('tipo') == 'ficha') + 1} ({origem}): {len(mudou)} campo(s) {'novo(s)' if not anterior else 'alterado(s)'}",
              "\n".join(linhas), {"ficha": atual, "mudou": mudou})


def exportar_md(cfg: nucleo.Config) -> Path:
    evs = ler(cfg)
    linhas = [f"# Trilha da conversa ({dt.datetime.now().strftime('%Y-%m-%d %H:%M')})", "", f"{len(evs)} eventos", ""]
    for i, e in enumerate(evs, 1):
        linhas.append(f"## {i}. [{e['t']}] {e['tipo']}: {nucleo.inline(e['titulo'])}")
        if e.get("detalhe"):
            linhas += [""] + nucleo.cerca(e["detalhe"])
        linhas.append("")
    ult = next((e["ficha"] for e in reversed(evs) if e.get("tipo") == "ficha" and e.get("ficha")), None)
    if ult:
        linhas += ["## Ficha final", ""] + [f"- **{k}**: {nucleo.inline(v)}" for k, v in ult.items() if v]
    p = cfg.saida / f"trilha_{dt.datetime.now().strftime('%Y%m%d_%H%M')}.md"
    p.write_text("\n".join(linhas) + "\n", encoding="utf-8", newline="\n")
    return p


_PAGINA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>cdflw: trilha da conversa</title>
<style>
 body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#f6f7f9;color:#222;display:flex;height:100vh;overflow:hidden}
 #linha{width:52%;overflow:auto;padding:14px;box-sizing:border-box}
 #lado{flex:1;overflow:auto;padding:14px;box-sizing:border-box;background:#fff;border-left:1px solid #ddd}
 h1{font-size:16px;margin:0 0 4px}.dica{color:#777;font-size:11px}
 .ev{display:flex;gap:10px;margin:6px 0;cursor:pointer}.ev:hover .caixa{background:#eef3fa}
 .hora{width:62px;color:#777;font-size:11px;padding-top:7px;text-align:right}
 .ponto{width:12px;height:12px;border-radius:50%;margin-top:7px;flex:none;border:2px solid #fff;box-shadow:0 0 0 1px #bbb}
 .caixa{flex:1;background:#fff;border:1px solid #ddd;border-radius:6px;padding:6px 10px;font-size:13px}
 .caixa b{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#555;margin-right:6px}
 .resumo{color:#444;font-size:12px;white-space:pre-wrap;max-height:60px;overflow:hidden}
 .fio{position:absolute;left:0;top:0}
 pre{background:#f1f4f8;padding:8px;border-radius:4px;font-size:12px;white-space:pre-wrap;word-break:break-word}
 .add{color:#2b7a3d}.del{color:#b00020}.chg{color:#1a4d8f}
 #ficha td{vertical-align:top;padding:2px 6px;font-size:12px;border-bottom:1px solid #eee}#ficha td:first-child{color:#555;white-space:nowrap}
 .mudou{background:#fff7d6}
 #stats span{display:inline-block;margin-right:10px;font-size:12px}#stats i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:3px}
</style></head><body>
<div id="linha"><h1>Trilha da conversa</h1><div class="dica">__GERADO__ · recarrega sozinho a cada 2 s · clique num evento para ver tudo</div><div id="stats"></div><div id="eventos"></div></div>
<div id="lado"><h1 id="tit">Ficha atual</h1><div id="conteudo"></div></div>
<script>
const E = __EVENTOS__; const C = __CORES__;
const tipos = {}; E.forEach(e => tipos[e.tipo] = (tipos[e.tipo] || 0) + 1);
document.getElementById('stats').innerHTML = Object.entries(tipos).map(([k, n]) => `<span><i style="background:${C[k] || '#999'}"></i>${k}: ${n}</span>`).join('');
const esc = s => (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
document.getElementById('eventos').innerHTML = E.map((e, i) => `<div class="ev" onclick="ver(${i})"><div class="hora">${e.t}</div><div class="ponto" style="background:${C[e.tipo] || '#999'}"></div><div class="caixa"><b>${e.tipo}</b>${esc(e.titulo)}${e.detalhe ? `<div class="resumo">${esc(e.detalhe.slice(0, 220))}${e.detalhe.length > 220 ? ' …' : ''}</div>` : ''}</div></div>`).join('');
function ver(i) { const e = E[i]; document.getElementById('tit').textContent = `${e.t} · ${e.tipo} · ${e.titulo}`; document.getElementById('conteudo').innerHTML = e.ficha ? tabelaFicha(e.ficha, e.mudou || []) + (e.detalhe ? `<pre>${colorir(esc(e.detalhe))}</pre>` : '') : `<pre>${esc(e.detalhe || '(sem detalhe)')}</pre>`; localStorage.setItem('cdflw_trilha_sel', i); }
function colorir(t) { return t.split('\\n').map(l => l.startsWith('+') ? `<span class="add">${l}</span>` : l.startsWith('-') ? `<span class="del">${l}</span>` : l.startsWith('~') ? `<span class="chg">${l}</span>` : l).join('\\n'); }
function tabelaFicha(f, mudou) { return '<table id="ficha">' + Object.entries(f).filter(([k, v]) => v).map(([k, v]) => `<tr class="${mudou.includes(k) ? 'mudou' : ''}"><td>${k}</td><td>${esc(v)}</td></tr>`).join('') + '</table>'; }
const ult = [...E].reverse().find(e => e.ficha); if (ult) { document.getElementById('conteudo').innerHTML = tabelaFicha(ult.ficha, ult.mudou || []); }
const sel = localStorage.getItem('cdflw_trilha_sel'); if (sel !== null && E[sel]) ver(+sel);
window.scrollTo(0, 0); const le = document.getElementById('linha'); le.scrollTop = le.scrollHeight;
setTimeout(() => location.reload(), 2000);
</script></body></html>
"""


def gerar_html(cfg: nucleo.Config) -> Path:
    evs = ler(cfg)
    pagina = (_PAGINA.replace("__EVENTOS__", json.dumps(evs, ensure_ascii=False).replace("</", "<\\/"))
              .replace("__CORES__", json.dumps(TIPOS)).replace("__GERADO__", dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    p = _html(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(pagina, encoding="utf-8", newline="\n")
    return p


# ==========================================================================================
# __main__: Linha de comando do cdflw. E o que o agente do Copilot chama.
# ==========================================================================================





_ARQUIVO_SAIDA: Path | None = None  # copia de tudo que o comando imprime, para o agente ler se o terminal falhar


def _p(msg: str = "") -> None:
    print(msg, flush=True)
    if _ARQUIVO_SAIDA is not None:
        try:
            with _ARQUIVO_SAIDA.open("a", encoding="utf-8", newline="\n") as f:
                f.write(msg + "\n")
        except OSError:
            pass


def _ler_regra(caminho: str) -> dict[str, Any]:
    p = Path(caminho)
    if not p.exists():
        raise SystemExit(f"arquivo nao encontrado: {p}")
    r = json.loads(p.read_text(encoding="utf-8-sig"))
    if not isinstance(r, dict):
        raise SystemExit("a ficha precisa ser um objeto JSON com os campos da regra")
    return nucleo.completar({**nucleo.regra_vazia(), **r})


def _contexto(cfg: nucleo.Config, pedido: str = "", em_criacao: set[str] | None = None, nova: bool = False) -> nucleo.Contexto:
    snap, extras = catalogo.carregar_snapshot(cfg), catalogo.carregar_extras(cfg)
    siglas = set(catalogo.indice_colunas(snap, extras)) | {g["sigla"].upper() for g in nucleo.ler_glossario_csv(cfg.dados / "glossario.csv")}
    regras = nucleo.ler_jsonl(cfg.dados / "regras.jsonl") + nucleo.ler_jsonl(cfg.dados / "regras_novas.jsonl")
    kb_p = cfg.dados / "base_conhecimento.json"
    kb = json.loads(kb_p.read_text(encoding="utf-8")) if kb_p.exists() else {}
    return nucleo.Contexto(siglas_conhecidas=siglas, codigos_existentes={c for c in nucleo.codigos_usados(regras)},
                            campos_obrigatorios=nucleo.campos_obrigatorios_da_base(kb) if kb else None,
                            pedido=pedido, codigos_em_criacao=em_criacao or set(), nova=nova,
                            tabelas_conhecidas=set(catalogo.tabelas_unificadas(snap, extras)) | {v.lower() for v in cfg.mapa_uc.values()})


# ---------------------------------------------------------------------------
def cmd_instalar(cfg: nucleo.Config, a) -> int:
    for p in (cfg.base, cfg.dados, cfg.saida, cfg.fichas, cfg.dados / "uc"):
        p.mkdir(parents=True, exist_ok=True)
    faltam = nucleo.instalar_copilot(cfg)
    _p(f"Pastas prontas em {cfg.raiz}")
    if faltam:
        _p(f"ATENCAO: faltam no {cfg.copilot_fonte}: {', '.join(faltam)} (copie os arquivos do Copilot para la)")
    else:
        _p(f"Copilot: agente e skills encontrados em {cfg.copilot_fonte}; instrucoes e settings ajustados")
    _p(f"Databricks: profile '{cfg.profile}', cluster '{cfg.cluster_id or '(nao encontrado)'}', {cfg.catalogo or '?'}.{cfg.schema or '?'}")
    if not cfg.catalogo or not cfg.schema:
        _p("  ATENCAO: catalogo/schema vazios. Rode: python -m cdflw configurar --uc catalogo.schema")
    _p()
    _p("Proximos passos:")
    _p(f"  1. Copie os arquivos da Governanca para {cfg.base}")
    _p("     (Regras de governanca.md, regras_aprovadas_*.md e, se tiver, o export do CadFlow em .xlsx)")
    _p("  2. No Copilot Chat, rode /atualizar  (ou: python -m cdflw atualizar)")
    _p("  3. Depois, escolha o agente @cdflw e use /nova-regra")
    return 0


def cmd_configurar(cfg: nucleo.Config, a) -> int:
    arq = "config.local.toml" if a.local else "config.toml"
    gv = lambda secao, chave, valor: nucleo.gravar_valor(cfg.raiz, secao, chave, valor, arq)  # noqa: E731
    if a.uc:
        if "." not in a.uc:
            _p("use --uc catalogo.schema (ex.: meu_catalogo.meu_schema)")
            return 1
        cat, sch = a.uc.split(".", 1)
        gv("databricks", "catalogo", cat.strip())
        gv("databricks", "schema", sch.strip())
    if a.profile:
        gv("databricks", "profile", a.profile)
    if a.cluster:
        gv("databricks", "cluster_id", a.cluster)
    if a.warehouse:
        gv("databricks", "warehouse_id", a.warehouse)
    if a.cluster_nome or a.warehouse_nome:
        cfg = nucleo.carregar(cfg.raiz)
        rec = catalogo.listar_recursos(cfg)
        if a.cluster_nome:
            cid = catalogo.resolver_por_nome(rec["clusters"], a.cluster_nome)
            if cid:
                gv("databricks", "cluster_id", cid)
                _p(f"cluster '{a.cluster_nome}' -> {cid}")
            else:
                _p(f"cluster '{a.cluster_nome}' nao encontrado ou ambiguo. Veja: python -m cdflw recursos")
                return 1
        if a.warehouse_nome:
            wid = catalogo.resolver_por_nome(rec["warehouses"], a.warehouse_nome)
            if wid:
                gv("databricks", "warehouse_id", wid)
                _p(f"warehouse '{a.warehouse_nome}' -> {wid}")
            else:
                _p(f"warehouse '{a.warehouse_nome}' nao encontrado ou ambiguo. Veja: python -m cdflw recursos")
                return 1
    if a.modelo:
        gv("copilot", "modelo", a.modelo)
        if nucleo.trocar_modelo(cfg, a.modelo):
            _p(f"agente do Copilot agora usa o modelo '{a.modelo}' (recarregue a janela do VS Code)")
    if a.aceitar_mapa:
        cfg = nucleo.carregar(cfg.raiz)
        regras = nucleo.ler_jsonl(cfg.dados / "regras.jsonl")
        snap = catalogo.carregar_snapshot(cfg)
        if not regras:
            _p("sem dados/regras.jsonl: rode /atualizar antes de aceitar o mapa")
            return 1
        m = nucleo.mapa_final(cfg, regras, snap)
        n = 0
        for sig, v in m.items():
            if v["prefixo"] and not v["prefixo_confirmado"]:
                gv("mapa_tabelas.prefixo", sig, v["prefixo"]); n += 1
            if v["tabela_uc"] and not v["tabela_uc_confirmada"]:
                gv("mapa_tabelas.uc", sig, v["tabela_uc"]); n += 1
        _p(f"mapa: {n} valor(es) gravados em config.toml ([mapa_tabelas.prefixo] e [mapa_tabelas.uc]). Edite la o que discordar.")
    cfg = nucleo.carregar(cfg.raiz)
    _p(f"config.toml: catalogo.schema = {cfg.catalogo or '?'}.{cfg.schema or '?'} | profile = {cfg.profile} | cluster = {cfg.cluster_id or '?'} | warehouse = {cfg.warehouse_id or '-'} | modelo = {cfg.modelo} | mapa confirmado: {len(cfg.prefixos)} prefixos, {len(cfg.mapa_uc)} tabelas")
    return 0


RC_CLUSTER_PENDENTE = 2  # "ainda iniciando / desligado": o agente deve esperar e repetir, nao desistir


def cmd_cluster(cfg: nucleo.Config, a) -> int:
    try:
        w = catalogo._cliente(cfg)
        if a.ligar:
            e = catalogo.ligar_cluster(cfg, w)
            _p(f"cluster {e['nome'] or e['id']}: {e['estado']} (pedido de ligar enviado; all-purpose leva alguns minutos)")
        if a.esperar or a.ligar:
            e = catalogo.esperar_cluster(cfg, w, a.max, _p)
        else:
            e = catalogo.estado_cluster(cfg, w)
    except Exception as ex:  # noqa: BLE001
        _p(f"nao consegui consultar o cluster: {type(ex).__name__}: {ex}")
        return 1
    _p(f"cluster {e['nome'] or e['id']}: {e['estado']}" + (f" ({e['mensagem']})" if e["mensagem"] else ""))
    if e["estado"] in catalogo.ESTADOS_RODANDO:
        _p("pronto: os comandos de dado (perfil, testar-regra, exemplos, dominio, sobreposicao) podem rodar.")
        return 0
    if e["estado"] in catalogo.ESTADOS_SUBINDO:
        _p(f"ainda subindo. Rode de novo: python -m cdflw cluster --esperar --max {a.max or cfg.espera_cluster_s}")
        return RC_CLUSTER_PENDENTE
    _p("parado. Para ligar: python -m cdflw cluster --ligar   (ou configure um SQL warehouse: python -m cdflw recursos)")
    return RC_CLUSTER_PENDENTE


def cmd_recursos(cfg: nucleo.Config, a) -> int:
    rec = catalogo.listar_recursos(cfg)
    _p(f"profile {cfg.profile}")
    _p("clusters:")
    for c in rec["clusters"]:
        _p(f"  {c['id']:<22} {c['estado']:<12} {c['nome']}")
    _p("sql warehouses:")
    for w in rec["warehouses"]:
        _p(f"  {w['id']:<22} {w['estado']:<12} {w['nome']}")
    _p()
    _p('Para usar: python -m cdflw configurar --cluster-nome "<nome>"   ou   --warehouse-nome "<nome>"')
    _p("(o warehouse, se existir, roda a linhagem sem precisar ligar o cluster)")
    return 0


VERSAO = "2026-10-29 17:00"


def _versao(cfg: nucleo.Config) -> str:
    return VERSAO


def cmd_status(cfg: nucleo.Config, a) -> int:
    _p(f"cdflw versao {_versao(cfg)}")
    arq = nucleo.descobrir_arquivos(cfg.base)
    _p(f"base/: conhecimento={len(arq['conhecimento'])} aprovadas={len(arq['aprovadas'])} export={len(arq['export'])}")
    regras = nucleo.ler_jsonl(cfg.dados / "regras.jsonl")
    novas = nucleo.ler_jsonl(cfg.dados / "regras_novas.jsonl")
    snap = catalogo.carregar_snapshot(cfg)
    lin = catalogo.carregar_linhagem(cfg)
    _p(f"dados/: regras={len(regras)} novas={len(novas)} glossario={len(nucleo.ler_glossario_csv(cfg.dados / 'glossario.csv'))}")
    if novas:
        por_lote: dict[str, list[str]] = {}
        for r in novas:
            por_lote.setdefault(str(r.get("lote", "-")), []).append(f"{r.get('codigo', '?')} ({r.get('modelo_usado', '?')})")
        for lote, cods in list(por_lote.items())[-6:]:
            _p(f"  lote {lote}: " + ", ".join(cods))
    _p(f"catalogo: {snap.get('catalogo', '?')}.{snap.get('schema', '?')} snapshot={snap.get('snapshot_id', 'nenhum')} tabelas={len(snap.get('tabelas', {}))} linhagem={len(lin.get('relacoes', {}))} colunas com origem")
    extras = catalogo.carregar_extras(cfg)
    met = grafo.carregar_metricas(cfg)
    _p(f"tabelas incluidas sob demanda: {len(extras)} | metricas do grafo: {met.get('gerado_em', 'nenhuma (rode /atualizar)')}")
    if a.cluster:
        try:
            e = catalogo.estado_cluster(cfg)
            _p(f"cluster: {e['nome'] or e['id'] or '-'}: {e['estado']}" + ("  (warehouse configurado: preferido para SQL)" if cfg.warehouse_id else ""))
        except Exception as ex:  # noqa: BLE001
            _p(f"cluster: nao consultado ({type(ex).__name__})")
    _p(f"saida: {cfg.excel_saida} ({'existe' if cfg.excel_saida.exists() else 'ainda nao criado'})")
    return 0


def cmd_atualizar(cfg: nucleo.Config, a) -> int:
    arq = nucleo.descobrir_arquivos(cfg.base)
    nao = cfg.nao_siglas
    _p(f"== base/ ({cfg.base})")
    kb: dict[str, Any] = {}
    for p in arq["conhecimento"]:
        kb = nucleo.ler_base_conhecimento(p)
        _p(f"  conhecimento: {p.name}: secoes {', '.join(f'{k}={len(v)}' for k, v in kb['secoes'].items()) or '(nenhum JSON por secao)'}")
    regras: list[dict[str, Any]] = []
    for p in arq["aprovadas"]:
        rs = nucleo.ler_aprovadas_md(p, nao)
        _p(f"  aprovadas: {p.name}: {len(rs)} regras")
        regras += rs
    for p in arq["export"]:
        try:
            rs = nucleo.ler_export_xlsx(p, nao)
            _p(f"  export: {p.name}: {len(rs)} linhas")
            regras += rs
        except Exception as e:  # noqa: BLE001
            _p(f"  export: {p.name}: NAO LIDO ({type(e).__name__}: {e})")
    if not regras and not kb:
        _p("  nada encontrado. Copie os arquivos da Governanca para base/ e rode de novo.")
    # desduplica por codigo (export vence o md porque tem mais campos), senao por nome
    por_chave: dict[str, dict[str, Any]] = {}
    for r in regras:
        k = r.get("codigo") or f"nome:{r.get('nome', '').lower()}"
        if k in por_chave and por_chave[k]["origem"] == "export_xlsx" and r["origem"] != "export_xlsx":
            continue
        por_chave[k] = r
    regras = list(por_chave.values())
    cfg.dados.mkdir(parents=True, exist_ok=True)
    nucleo.gravar_jsonl(cfg.dados / "regras.jsonl", regras)
    (cfg.dados / "base_conhecimento.json").write_text(json.dumps(kb, ensure_ascii=False, indent=1), encoding="utf-8")

    _p(f"== Unity Catalog {cfg.catalogo}.{cfg.schema} (profile {cfg.profile})")
    snap = catalogo.carregar_snapshot(cfg)
    lin = catalogo.carregar_linhagem(cfg)
    if not a.sem_uc:
        try:
            snap = catalogo.listar_tabelas(cfg, progresso=_p)
            catalogo.gravar_snapshot(cfg, snap)
            _p(f"  snapshot {snap['snapshot_id']}: {len(snap['tabelas'])} tabelas")
        except Exception as e:  # noqa: BLE001
            _p(f"  NAO consegui ler o catalogo ({type(e).__name__}: {e}). Seguindo com o snapshot anterior ({snap.get('snapshot_id', 'nenhum')}).")
        if cfg.quer_linhagem and not a.sem_linhagem:
            lin = catalogo.consultar_linhagem(cfg, progresso=_p)
            catalogo.gravar_linhagem(cfg, lin)
            for e in lin.get("erros", []):
                _p(f"  linhagem: tentativa falhou: {e}")
            _p(f"  linhagem: {len(lin.get('relacoes', {}))} colunas com origem conhecida")
        extras = catalogo.carregar_extras(cfg)
        if extras:
            _p(f"  reprocessando {len(extras)} tabela(s) incluida(s) sob demanda ...")
            try:
                w = catalogo._cliente(cfg)
                for fqn in list(extras):
                    t = catalogo.obter_tabela(cfg, fqn, w)
                    if t:
                        extras[fqn].update({k: t[k] for k in ("colunas", "comentario", "tipo_tabela")})
                    else:
                        extras[fqn]["sumiu_do_catalogo"] = True
                        _p(f"    {fqn}: NAO existe mais no catalogo")
                catalogo.gravar_extras(cfg, extras)
            except Exception as e:  # noqa: BLE001
                _p(f"  extras nao reprocessados ({type(e).__name__}: {e})")
    else:
        _p("  pulado (--sem-uc)")
    extras = catalogo.carregar_extras(cfg)

    _p("== glossario e mapa")
    glos = nucleo.extrair_glossario(regras, catalogo.comentarios_colunas(snap))
    nucleo.gravar_glossario_csv(cfg.dados / "glossario.csv", glos)
    _p(f"  glossario: {len(glos)} siglas com termo de negocio")
    m = nucleo.mapa_final(cfg, regras, snap)
    (cfg.dados / "mapa_tabelas.md").write_text(nucleo.texto_mapa(m), encoding="utf-8", newline="\n")
    pendentes = [s for s, v in m.items() if not (v["prefixo_confirmado"] and v["tabela_uc_confirmada"])]
    _p(f"  mapa: {len(m)} siglas de tabela; {len(pendentes)} a confirmar no config.toml (veja dados/mapa_tabelas.md)")

    _p("== grafo e analise")
    todas = regras + nucleo.ler_jsonl(cfg.dados / "regras_novas.jsonl")
    g = grafo.construir(todas, set(catalogo.indice_colunas(snap, extras)) if snap else None)
    grafo.gravar(cfg.dados / "grafo.json", g)
    achados = grafo.detectar(g)
    (cfg.dados / "detectados.md").write_text(grafo.texto_detectados(achados), encoding="utf-8", newline="\n")
    _p(f"  {g.get('n_regras', 0)} regras com codigo, {len(g['arestas'])} relacoes, {len(achados)} problema(s) estrutural(is) em dados/detectados.md")
    met = grafo.calcular(cfg, g, todas, snap, extras)
    grafo.gravar_metricas(cfg, met)
    visoes = grafo.gravar_visoes(cfg, met)
    grafo.exportar_gexf(g, met, cfg.dados / "grafo.gexf")
    grafo.gerar(g, cfg.dados / "grafo.html", met)
    c = met["cadeias"]
    _p(f"  cadeias: {len(c['completas'])} completas, {len(c['quebradas'])} quebradas, {len(c['ciclos'])} ciclo(s) | redundancias: {len(met['redundancias'])} | comunidades: {len(met['comunidades']['grupos'])} ({met['comunidades']['metodo']}) | networkx: {'sim' if met['com_networkx'] else 'nao (pip install networkx para comunidades e intermediacao)'}")
    _p(f"  visoes em dados/visoes/ ({len(visoes)} arquivos); grafo navegavel em {cfg.dados / 'grafo.html'}; Gephi/Cytoscape: dados/grafo.gexf")

    _p("== calibracao do validador contra as aprovadas")
    ctx = _contexto(cfg)
    ctx.codigos_existentes = set()  # as proprias aprovadas nao podem acusar 'codigo repetido'
    aprovadas = [r for r in regras if (r.get("status") or "").lower().startswith("aprov") or r.get("origem") == "aprovadas_md"]
    cal = nucleo.calibrar(aprovadas, cfg, ctx)
    (cfg.dados / "calibracao.json").write_text(json.dumps(cal, ensure_ascii=False, indent=1), encoding="utf-8")
    _p(f"  {cal['total']} aprovadas; {len(cal['reprovadas'])} reprovadas pelo validador (se > 0, o validador esta errado: veja dados/calibracao.json); {len(cal['incompletas_na_fonte'])} com campo vazio na fonte")
    for ck, n in cal["por_check"].items():
        _p(f"    {ck}: {n}")

    _p("== referencias da skill e publicacao")
    escritos = nucleo.gerar(cfg, kb, aprovadas or regras, glos, snap, m)
    faltam = nucleo.instalar_copilot(cfg)
    _p(f"  {len(escritos)} referencias geradas em {cfg.copilot_fonte / 'skills' / 'regras-cadflow' / 'references'}" + (f"; FALTAM: {', '.join(faltam)}" if faltam else ""))
    _p()
    _p("Pronto. No Copilot Chat: agente @cdflw, prompt /nova-regra.")
    return 0


def cmd_campo(cfg: nucleo.Config, a) -> int:
    snap, lin, extras = catalogo.carregar_snapshot(cfg), catalogo.carregar_linhagem(cfg), catalogo.carregar_extras(cfg)
    glos = {g["sigla"].upper(): g for g in nucleo.ler_glossario_csv(cfg.dados / "glossario.csv")}
    if not snap:
        _p("sem snapshot do catalogo: rode /atualizar")
    for s in a.siglas:
        for l in catalogo.descrever_campo(snap, lin, s, extras):
            _p(l)
        if s.upper() in glos:
            _p(f"    glossario: {glos[s.upper()]['termo_negocio']} (fonte {glos[s.upper()]['fonte']})")
        g = grafo.carregar(cfg.dados / "grafo.json")
        rel = grafo.relacionadas(g, [s])
        for r in rel[:8]:
            _p(f"    regra {r['codigo']} ({r['tipo']}): {r['nome'][:70]} [{'; '.join(r['motivos'])}]")
    return 0


def cmd_tabela(cfg: nucleo.Config, a) -> int:
    snap, extras = catalogo.carregar_snapshot(cfg), catalogo.carregar_extras(cfg)
    nome = cfg.mapa_uc.get(a.nome.upper(), a.nome)
    for l in catalogo.descrever_tabela(snap, nome, a.limite, extras):
        _p(l)
    return 0


def cmd_relacionadas(cfg: nucleo.Config, a) -> int:
    g = grafo.carregar(cfg.dados / "grafo.json")
    campos = [c.strip() for c in (a.campos or "").split(",") if c.strip()]
    rel = grafo.relacionadas(g, campos, a.tabela or "", a.tipo or "")
    if not rel:
        _p("nenhuma regra existente toca esses campos/tabela")
    for r in rel[:a.limite]:
        alerta = f"  <-- {r['alerta']}" if r["alerta"] else ""
        _p(f"{r['codigo']} ({r['tipo']}, {r['tabela_sigla']}): {r['nome'][:80]} [{'; '.join(r['motivos'])}]{alerta}")
    return 0


def cmd_proximo_codigo(cfg: nucleo.Config, a) -> int:
    regras = nucleo.ler_jsonl(cfg.dados / "regras.jsonl") + nucleo.ler_jsonl(cfg.dados / "regras_novas.jsonl")
    usados = nucleo.codigos_usados(regras)
    pfx = a.prefixo or cfg.prefixos.get(a.tabela.upper(), "")
    if not pfx and a.tabela.upper() in cfg.prefixos.values():
        pfx = a.tabela.upper()  # o agente passou o prefixo (BPJ) em vez da sigla da tabela: aceita
        _p(f"(interpretei '{a.tabela}' como prefixo)")
    if not pfx:
        sug = nucleo.inferir_prefixos(regras).get(a.tabela.upper(), {}).get("prefixo", "")
        if not sug:
            _p(f"tabela {a.tabela} sem prefixo conhecido. Informe --prefixo XXX ou confirme em config.toml [mapa_tabelas.prefixo]")
            return 1
        _p(f"(prefixo {sug} inferido das regras existentes; confirme em config.toml)")
        pfx = sug
    tipo = nucleo._canon(a.tipo, cfg.tipos) or a.tipo
    try:
        r = nucleo.proximo(pfx, tipo, cfg, usados, a.rn or "")
    except ValueError as e:
        _p(str(e))
        return 1
    _p(json.dumps(r, ensure_ascii=False))
    return 0


def cmd_validar(cfg: nucleo.Config, a) -> int:
    regra = _ler_regra(a.ficha)
    registrar_ficha(cfg, regra, "validar")
    em_criacao = {c.strip().upper() for c in (a.junto or "").split(",") if c.strip()}
    ctx = _contexto(cfg, a.pedido or "", em_criacao, nova=True)
    ach = nucleo.validar(regra, cfg, ctx)
    _p(nucleo.resumo(ach))
    return 1 if any(x.nivel == "erro" for x in ach) else 0


def cmd_gravar(cfg: nucleo.Config, a) -> int:
    regra = nucleo.canonizar(_ler_regra(a.ficha), cfg)
    registrar_ficha(cfg, regra, "gravar")
    ctx = _contexto(cfg, nova=True)
    ach = nucleo.validar(regra, cfg, ctx)
    erros = [x for x in ach if x.nivel == "erro"]
    if erros and not a.forcar:
        _p("NAO gravado: a regra tem erros. Corrija ou use --forcar.")
        _p(nucleo.resumo(ach))
        return 1
    regra["modelo_usado"] = regra.get("modelo_usado") or cfg.modelo
    regra["status"] = "rascunho"
    regra["lote"] = regra.get("lote") or nucleo.lote_atual(cfg)
    px = nucleo.gravar_excel(regra, cfg)
    pf = nucleo.gravar_ficha(regra, cfg)
    nucleo.gravar_rascunho_jsonl(regra, cfg)
    _regenerar_grafo(cfg)
    registrar(cfg, "gravou", f"{regra.get('codigo', '')} {regra.get('nome', '')}", f"Excel: {px}\nFicha: {pf}", regerar=False)
    if regra.get("teste_no_dado"):
        _p(f"Teste : {regra['teste_no_dado']}")
    _p(f"Excel : {px}")
    _p(f"Ficha : {pf}")
    _p(f"Lote  : {regra['lote']} (para desfazer tudo desta rodada: python -m cdflw desfazer --lote {regra['lote']})")
    _p(f"Grafo : {cfg.dados / 'grafo.html'} (procure por {regra.get('codigo', '')})")
    if ach:
        _p("Avisos que ficaram para o revisor:")
        _p(nucleo.resumo(ach))
    return 0


def _regenerar_grafo(cfg: nucleo.Config) -> None:
    regras = nucleo.ler_jsonl(cfg.dados / "regras.jsonl") + nucleo.ler_jsonl(cfg.dados / "regras_novas.jsonl")
    snap = catalogo.carregar_snapshot(cfg)
    extras = catalogo.carregar_extras(cfg)
    g = grafo.construir(regras, set(catalogo.indice_colunas(snap, extras)) if snap else None)
    grafo.gravar(cfg.dados / "grafo.json", g)
    met = grafo.carregar_metricas(cfg)
    grafo.gerar(g, cfg.dados / "grafo.html", met)


# ---------------------------------------------------------------------------
# tabelas sob demanda e teste no dado
# ---------------------------------------------------------------------------
def cmd_incluir_tabela(cfg: nucleo.Config, a) -> int:
    siglas = {s.strip().upper() for s in (a.siglas or "").split(",") if s.strip()}
    rel = catalogo.incluir_tabela(cfg, a.fqn, siglas, similares=not a.sem_similares, linhagem=a.linhagem, progresso=_p)
    for l in catalogo.texto_inclusao(rel):
        _p(l)
    if rel.get("erro"):
        return 1
    _regenerar_grafo(cfg)
    return 0


def _fqn_ou_erro(cfg: nucleo.Config, nome: str) -> str:
    fqn = catalogo.resolver_fqn(cfg, nome)
    if not fqn:
        _p(f"tabela '{nome}' nao resolvida. Use catalogo.schema.tabela, ou rode: python -m cdflw incluir-tabela <fqn>")
    return fqn


def cmd_perfil(cfg: nucleo.Config, a) -> int:
    fqn = _fqn_ou_erro(cfg, a.tabela)
    if not fqn:
        return 1
    try:
        p = catalogo.perfil(cfg, fqn, a.campo, mascarar=cfg.mascarar_amostras and not a.sem_mascara, progresso=_p)
    except catalogo.SqlInvalido as e:
        _p(f"recusado: {e}")
        return 1
    except (catalogo.ClusterDesligado, catalogo.ClusterIniciando) as e:
        _p(f"CLUSTER PENDENTE: {e}")
        _p("nao desista: espere com `python -m cdflw cluster --esperar` e repita este comando.")
        return RC_CLUSTER_PENDENTE
    for l in catalogo.texto_perfil(p):
        _p(l)
    return 0 if not p.get("erro") else 1


def cmd_testar_regra(cfg: nucleo.Config, a) -> int:
    regra = _ler_regra(a.ficha)
    pred = a.predicado or regra.get("sql_teste", "")
    tabela = a.tabela or regra.get("tabela_uc", "") or cfg.mapa_uc.get((regra.get("tabela_sigla") or "").upper(), "")
    if not pred or not tabela:
        _p("preciso do predicado (chave sql_teste na ficha ou --predicado) e da tabela (chave tabela_uc na ficha, mapa da sigla, ou --tabela)")
        return 1
    fqn = _fqn_ou_erro(cfg, tabela)
    if not fqn:
        return 1
    try:
        t = catalogo.testar_predicado(cfg, fqn, pred, progresso=_p)
    except catalogo.SqlInvalido as e:
        _p(f"recusado: {e}")
        return 1
    except (catalogo.ClusterDesligado, catalogo.ClusterIniciando) as e:
        _p(f"CLUSTER PENDENTE: {e}")
        _p("nao desista: espere com `python -m cdflw cluster --esperar` e repita este comando.")
        return RC_CLUSTER_PENDENTE
    for l in catalogo.texto_teste(t):
        _p(l)
    if t.get("erro"):
        return 1
    # grava o resultado na propria ficha, para o gravar levar ao Excel
    regra["teste_no_dado"] = f"{t['marcados']} de {t['total']} ({t['taxa']:.2%}) em {t['testado_em']}"
    regra["tabela_uc"] = fqn
    regra["sql_teste"] = pred
    Path(a.ficha).write_text(json.dumps({k: v for k, v in regra.items() if k not in ("campos", "dominios", "flags", "extras", "origem")}, ensure_ascii=False, indent=1), encoding="utf-8")
    _p("resultado gravado na ficha (teste_no_dado).")
    return 0


def cmd_exemplos(cfg: nucleo.Config, a) -> int:
    fqn = _fqn_ou_erro(cfg, a.tabela)
    if not fqn:
        return 1
    try:
        r = catalogo.exemplos(cfg, fqn, a.campo, a.onde or "", a.n, mascarar=cfg.mascarar_amostras and not a.sem_mascara, progresso=_p)
    except catalogo.SqlInvalido as e:
        _p(f"recusado: {e}")
        return 1
    except (catalogo.ClusterDesligado, catalogo.ClusterIniciando) as e:
        _p(f"CLUSTER PENDENTE: {e}")
        _p("nao desista: espere com `python -m cdflw cluster --esperar` e repita este comando.")
        return RC_CLUSTER_PENDENTE
    _p(f"{fqn}.{a.campo}" + (" (mascarado)" if r["mascarado"] else ""))
    _p("  atendem: " + (", ".join(r["atendem"]) or "-"))
    if a.onde:
        _p("  nao atendem: " + (", ".join(r["nao_atendem"]) or "-"))
    for e in r["erros"]:
        _p(f"  aviso: {e}")
    return 0


def cmd_dominio(cfg: nucleo.Config, a) -> int:
    try:
        r = catalogo.dominio(cfg, a.tabela, a.campo or "", a.n, progresso=_p)
    except catalogo.SqlInvalido as e:
        _p(f"recusado: {e}")
        return 1
    except (catalogo.ClusterDesligado, catalogo.ClusterIniciando) as e:
        _p(f"CLUSTER PENDENTE: {e}")
        _p("nao desista: espere com `python -m cdflw cluster --esperar` e repita este comando.")
        return RC_CLUSTER_PENDENTE
    if r.get("erro"):
        _p(r["erro"])
        return 1
    _p(f"{r['tabela']}.{r['campo']}: {len(r['valores'])} valor(es)" + (f" (via {r['via']})" if r.get("via") else ""))
    _p("  " + ", ".join(r["valores"][:a.n]))
    return 0


def cmd_sobreposicao(cfg: nucleo.Config, a) -> int:
    regra = _ler_regra(a.ficha)
    pred = regra.get("sql_teste", "")
    tabela = regra.get("tabela_uc", "") or cfg.mapa_uc.get((regra.get("tabela_sigla") or "").upper(), "")
    outra = next((r for r in nucleo.ler_jsonl(cfg.dados / "regras_novas.jsonl") + nucleo.ler_jsonl(cfg.dados / "regras.jsonl") if r.get("codigo") == a.com.upper()), None)
    pred_outra = a.predicado_outra or (outra or {}).get("sql_teste", "")
    if not (pred and tabela and pred_outra):
        _p("preciso de sql_teste e tabela_uc na ficha, e do predicado da outra regra (sql_teste dela ou --predicado-outra)")
        return 1
    fqn = _fqn_ou_erro(cfg, tabela)
    if not fqn:
        return 1
    try:
        r = catalogo.sobreposicao(cfg, fqn, pred, pred_outra, progresso=_p)
    except catalogo.SqlInvalido as e:
        _p(f"recusado: {e}")
        return 1
    except (catalogo.ClusterDesligado, catalogo.ClusterIniciando) as e:
        _p(f"CLUSTER PENDENTE: {e}")
        _p("nao desista: espere com `python -m cdflw cluster --esperar` e repita este comando.")
        return RC_CLUSTER_PENDENTE
    if r.get("erro"):
        _p(r["erro"])
        return 1
    _p(f"{fqn}: nova marca {r['novo']}, {a.com} marca {r['outro']}, ambas {r['ambos']} ({r['taxa_do_novo_ja_coberta']:.1%} do que a nova marca ja e coberto)")
    return 0


# ---------------------------------------------------------------------------
# visoes do grafo
# ---------------------------------------------------------------------------
def _grafo_e_metricas(cfg: nucleo.Config):
    g = grafo.carregar(cfg.dados / "grafo.json")
    met = grafo.carregar_metricas(cfg)
    if not met:
        _p("sem metricas: rode /atualizar (ou python -m cdflw atualizar --sem-uc) antes.")
    return g, met


def cmd_explorar(cfg: nucleo.Config, a) -> int:
    g, met = _grafo_e_metricas(cfg)
    for l in grafo.explorar(g, met, a.alvo):
        _p(l)
    return 0


def cmd_impacto(cfg: nucleo.Config, a) -> int:
    g, _met = _grafo_e_metricas(cfg)
    r = grafo.impacto(g, a.alvo, a.profundidade)
    if r.get("erro"):
        _p(f"{a.alvo}: {r['erro']}")
        return 1
    _p(f"impacto de {r['alvo']} (ate {a.profundidade} saltos): {len(r['regras_afetadas'])} regra(s), {len(r['campos_afetados'])} campo(s)")
    for x in r["regras_afetadas"]:
        _p(f"  d{x['distancia']} {x['regra']} ({x['tipo']}): {x['nome'][:70]}")
    if r["campos_afetados"]:
        _p("  campos: " + ", ".join(f"{x['campo']}(d{x['distancia']})" for x in r["campos_afetados"][:20]))
    return 0


def cmd_redundancias(cfg: nucleo.Config, a) -> int:
    g, _met = _grafo_e_metricas(cfg)
    pares = grafo.redundancias(g, a.limiar)
    _p(f"{len(pares)} par(es) com similaridade de campos >= {a.limiar}")
    for p in pares[:a.limite]:
        _p(f"  {p['classe']:<22} {p['a']} x {p['b']} ({p['tipo']}): campos {p['jaccard_campos']}, condicao {p['jaccard_condicao'] if p['jaccard_condicao'] is not None else '-'}: {', '.join(p['campos_comuns'][:5])}")
    return 0


def cmd_cadeias(cfg: nucleo.Config, a) -> int:
    g, _met = _grafo_e_metricas(cfg)
    c = grafo.cadeias(g)
    _p(f"completas {len(c['completas'])} | quebradas {len(c['quebradas'])} | ciclos {len(c['ciclos'])}")
    if not a.so_completas:
        for q in c["quebradas"][:a.limite]:
            _p(f"  QUEBRADA {q['validacao']} ({q['tabela']}): trata {', '.join(q['trata']) or '-'}; inexistentes {', '.join(q['inexistentes']) or '-'}")
    if not a.so_quebradas:
        for q in c["completas"][:a.limite]:
            _p(f"  ok {q['validacao']} -> {', '.join(q['trata'])}")
    for ciclo in c["ciclos"]:
        _p("  CICLO " + " -> ".join(ciclo))
    return 0


def cmd_cobertura(cfg: nucleo.Config, a) -> int:
    _g, met = _grafo_e_metricas(cfg)
    cb = met.get("cobertura", {})
    if a.tabela:
        t = a.tabela.upper()
        _p(f"{t}: {cb.get('por_tabela', {}).get(t, {})}")
        csr = cb.get("campos_sem_regra", {}).get(t)
        if csr:
            _p(f"  cobertura de campos {csr['cobertura']:.0%}; sem regra: {', '.join(csr['sem_regra'])}")
        return 0
    for t, v in sorted(cb.get("por_tabela", {}).items(), key=lambda kv: -kv[1]["regras"]):
        csr = cb.get("campos_sem_regra", {}).get(t, {})
        _p(f"  {t:<22} {v['regras']:>3} regras  {v['por_tipo']}  cobertura de campos {csr.get('cobertura', 0):.0%}" if csr else f"  {t:<22} {v['regras']:>3} regras  {v['por_tipo']}")
    sem = cb.get("tabelas_do_catalogo_sem_regra", [])
    _p(f"  tabelas do catalogo sem nenhuma regra: {len(sem)} (lista em dados/visoes/cobertura.md)")
    return 0


def cmd_dimensoes(cfg: nucleo.Config, a) -> int:
    _g, met = _grafo_e_metricas(cfg)
    d = met.get("dimensoes", {})
    dims = d.get("dimensoes", [])
    _p("tabela".ljust(22) + "".join(x[:12].ljust(13) for x in dims) + "n/class.")
    for t, v in sorted(d.get("matriz", {}).items()):
        _p(t.ljust(22) + "".join(str(v.get(x, 0)).ljust(13) for x in dims) + str(v.get("nao classificada", 0)))
    return 0


def cmd_exportar_grafo(cfg: nucleo.Config, a) -> int:
    g, met = _grafo_e_metricas(cfg)
    p = grafo.exportar_gexf(g, met, cfg.dados / "grafo.gexf")
    _p(f"GEXF: {p}  (abra no Gephi: File > Open; ou Cytoscape com o app GEXF)")
    return 0


# ---------------------------------------------------------------------------
# trilha da conversa
# ---------------------------------------------------------------------------
def cmd_anotar(cfg: nucleo.Config, a) -> int:
    if not ativa(cfg):
        _p("ok (trilha desligada)")
        return 0
    if a.leu:
        registrar(cfg, "leu", a.leu, a.texto or "")
    elif a.pergunta:
        registrar(cfg, "pergunta", a.pergunta, a.texto or "")
    elif a.resposta:
        registrar(cfg, "resposta", a.resposta, a.texto or "")
    elif a.erro:
        registrar(cfg, "erro", a.erro, a.texto or "")
    else:
        registrar(cfg, "conclusao", a.texto or "(vazio)")
    _p("ok")
    return 0


def cmd_trilha(cfg: nucleo.Config, a) -> int:
    if a.nova:
        nova(cfg, a.nova if a.nova != "-" else "")
        lote = nucleo.novo_lote(cfg)
        _p(f"trilha zerada: {cfg.saida / '_trilha.html'} | lote desta rodada: {lote}")
        return 0
    if a.limpar:
        limpar(cfg)
        _p("trilha apagada")
        return 0
    if a.exportar:
        _p(f"exportada: {exportar_md(cfg)}")
        return 0
    if a.ligar or a.desligar:
        nucleo.gravar_valor(cfg.raiz, "trilha", "ativa", "true" if a.ligar else "false")
        # gravar_valor escreve string; corrige para booleano toml
        p = cfg.raiz / "config.toml"
        p.write_text(p.read_text(encoding="utf-8").replace('ativa = "true"', "ativa = true").replace('ativa = "false"', "ativa = false"), encoding="utf-8", newline="\n")
        _p(f"trilha {'ligada' if a.ligar else 'desligada'}")
        return 0
    evs = ler(cfg)
    _p(f"trilha {'ativa' if ativa(cfg) else 'DESLIGADA'}: {len(evs)} evento(s); html: {cfg.saida / '_trilha.html'}")
    for e in evs[-a.limite:]:
        _p(f"  [{e['t']}] {e['tipo']:<9} {e['titulo']}")
    if a.abrir:
        import webbrowser
        gerar_html(cfg)
        webbrowser.open((cfg.saida / "_trilha.html").as_uri())
    return 0


def cmd_desfazer(cfg: nucleo.Config, a) -> int:

    novas = {nucleo.normalizar_codigo(r.get("codigo", "")): r for r in nucleo.criadas(cfg) if r.get("codigo")}
    pedidos = [nucleo.normalizar_codigo(c) for c in (a.codigos or [])]
    if a.lote:
        pedidos += nucleo.codigos_do_lote(a.lote, cfg)
        if not nucleo.codigos_do_lote(a.lote, cfg):
            _p(f"lote {a.lote} nao tem regras criadas pelo cdflw. Lotes existentes: {', '.join(sorted({str(r.get('lote', '')) for r in novas.values()})) or '-'}")
            return 1
    if not pedidos:
        _p("informe um ou mais codigos, --lote <id> ou --cadeia <codigo>. Veja: python -m cdflw status")
        return 1
    fora = [c for c in pedidos if c not in novas]
    for c in fora:
        na_base = any(nucleo.normalizar_codigo(r.get("codigo", "")) == c for r in nucleo.ler_jsonl(cfg.dados / "regras.jsonl"))
        _p(f"{c}: {'veio do export/aprovadas, nao foi criada pelo cdflw (edite no CadFlow)' if na_base else 'nao esta entre as regras criadas pelo cdflw'}; ignorada")
    alvo = [c for c in pedidos if c in novas]
    if a.cadeia:
        alvo = nucleo.expandir_cadeia(alvo, cfg)
    alvo = sorted(dict.fromkeys(alvo))
    if not alvo:
        return 1
    _p(f"{len(alvo)} regra(s) a desfazer:")
    for c in alvo:
        r = novas[c]
        _p(f"  {c} ({r.get('tipo', '?')}, lote {r.get('lote', '-')}): {r.get('nome', '')[:70]}")
    if a.listar:
        _p("(--listar: nada foi removido)")
        return 0
    total = {"registro": 0, "excel": 0, "fichas": 0}
    avisos: list[str] = []
    for c in alvo:
        r = nucleo.desfazer(c, cfg, manter_excel=a.manter_excel)
        total["registro"] += r["registro"]; total["excel"] += r["excel"]; total["fichas"] += int(r["ficha"])
        avisos += r["avisos"]
    _regenerar_grafo(cfg)
    registrar(cfg, "nota", f"desfez {', '.join(alvo)}", f"registro: {total['registro']} | excel: {total['excel']} | fichas: {total['fichas']}", regerar=False)
    _p(f"desfeitas: {total['registro']} registro(s), {total['excel']} linha(s) do Excel, {total['fichas']} ficha(s). Grafo refeito; codigos livres: {', '.join(alvo)}.")
    for av in dict.fromkeys(avisos):
        _p(f"  aviso: {av}")
    return 0 if not avisos else 1

def cmd_grafo_html(cfg: nucleo.Config, a) -> int:
    _regenerar_grafo(cfg)
    p = cfg.dados / "grafo.html"
    _p(f"grafo navegavel: {p}")
    if a.abrir:
        import webbrowser
        webbrowser.open(p.as_uri())
    return 0


def cmd_detectar(cfg: nucleo.Config, a) -> int:
    g = grafo.carregar(cfg.dados / "grafo.json")
    _p(grafo.texto_detectados(grafo.detectar(g)))
    return 0


# ---------------------------------------------------------------------------
def cfg_padrao_limiar() -> float:
    try:
        return nucleo.carregar().limiar_redundancia
    except SystemExit:
        return 0.6


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cdflw", description="assistente de regras CadFlow")
    ap.add_argument("--raiz", help="pasta do projeto (padrao: onde esta o pacote)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("instalar").set_defaults(fn=cmd_instalar)
    s = sub.add_parser("configurar"); s.add_argument("--uc", default="", help="catalogo.schema"); s.add_argument("--profile", default=""); s.add_argument("--cluster", default="", help="id do cluster"); s.add_argument("--cluster-nome", default="", help="nome do cluster (resolve o id)"); s.add_argument("--warehouse", default="", help="id do SQL warehouse"); s.add_argument("--warehouse-nome", default=""); s.add_argument("--modelo", default=""); s.add_argument("--aceitar-mapa", action="store_true", help="grava no config.toml o mapa sigla->prefixo->tabela sugerido pelo /atualizar"); s.add_argument("--local", action="store_true", help="grava em config.local.toml (so desta maquina; nao vai para o git)"); s.set_defaults(fn=cmd_configurar)
    sub.add_parser("recursos", help="lista clusters e SQL warehouses do profile").set_defaults(fn=cmd_recursos)
    s = sub.add_parser("status"); s.add_argument("--cluster", action="store_true", help="tambem consulta o estado do cluster (REST)"); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("cluster", help="estado do cluster; --ligar pede para ligar; --esperar espera ate RUNNING com progresso"); s.add_argument("--ligar", action="store_true"); s.add_argument("--esperar", action="store_true"); s.add_argument("--max", type=int, default=None, help="segundos maximos de espera (padrao: espera_cluster_s)"); s.set_defaults(fn=cmd_cluster)
    s = sub.add_parser("atualizar"); s.add_argument("--sem-uc", action="store_true"); s.add_argument("--sem-linhagem", action="store_true"); s.set_defaults(fn=cmd_atualizar)
    s = sub.add_parser("campo"); s.add_argument("siglas", nargs="+"); s.set_defaults(fn=cmd_campo)
    s = sub.add_parser("tabela"); s.add_argument("nome"); s.add_argument("--limite", type=int, default=80); s.set_defaults(fn=cmd_tabela)
    s = sub.add_parser("relacionadas"); s.add_argument("--campos", default=""); s.add_argument("--tabela", default=""); s.add_argument("--tipo", default=""); s.add_argument("--limite", type=int, default=15); s.set_defaults(fn=cmd_relacionadas)
    s = sub.add_parser("proximo-codigo"); s.add_argument("--tabela", required=True); s.add_argument("--tipo", required=True); s.add_argument("--rn", default=""); s.add_argument("--prefixo", default=""); s.set_defaults(fn=cmd_proximo_codigo)
    s = sub.add_parser("validar"); s.add_argument("ficha"); s.add_argument("--pedido", default=""); s.add_argument("--junto", default="", help="codigos criados na mesma conversa, separados por virgula"); s.set_defaults(fn=cmd_validar)
    s = sub.add_parser("gravar"); s.add_argument("ficha"); s.add_argument("--forcar", action="store_true"); s.set_defaults(fn=cmd_gravar)
    sub.add_parser("detectar").set_defaults(fn=cmd_detectar)
    s = sub.add_parser("incluir-tabela", help="traz uma tabela de outro schema para o indice (e as homonimas, ranqueadas)"); s.add_argument("fqn", help="catalogo.schema.tabela"); s.add_argument("--siglas", default="", help="siglas citadas no pedido, separadas por virgula (ajudam o ranking)"); s.add_argument("--sem-similares", action="store_true"); s.add_argument("--linhagem", action="store_true"); s.set_defaults(fn=cmd_incluir_tabela)
    s = sub.add_parser("perfil", help="perfil de um campo no dado (nulos, distintos, padroes, frequentes mascarados)"); s.add_argument("tabela"); s.add_argument("campo"); s.add_argument("--sem-mascara", action="store_true"); s.set_defaults(fn=cmd_perfil)
    s = sub.add_parser("testar-regra", help="quantos registros a regra marcaria (predicado SQL da ficha)"); s.add_argument("ficha"); s.add_argument("--predicado", default=""); s.add_argument("--tabela", default=""); s.set_defaults(fn=cmd_testar_regra)
    s = sub.add_parser("exemplos", help="amostra mascarada de valores que atendem / nao atendem um predicado"); s.add_argument("tabela"); s.add_argument("campo"); s.add_argument("--onde", default=""); s.add_argument("--n", type=int, default=5); s.add_argument("--sem-mascara", action="store_true"); s.set_defaults(fn=cmd_exemplos)
    s = sub.add_parser("dominio", help="confere que a tabela de dominio existe e lista os valores"); s.add_argument("tabela"); s.add_argument("--campo", default=""); s.add_argument("--n", type=int, default=50); s.set_defaults(fn=cmd_dominio)
    s = sub.add_parser("sobreposicao", help="registros marcados pela regra nova e por outra"); s.add_argument("ficha"); s.add_argument("--com", required=True, help="codigo da outra regra"); s.add_argument("--predicado-outra", default=""); s.set_defaults(fn=cmd_sobreposicao)
    s = sub.add_parser("explorar", help="tudo sobre um campo, tabela ou regra"); s.add_argument("alvo"); s.set_defaults(fn=cmd_explorar)
    s = sub.add_parser("impacto", help="quem e afetado se o alvo mudar"); s.add_argument("alvo"); s.add_argument("--profundidade", type=int, default=4); s.set_defaults(fn=cmd_impacto)
    s = sub.add_parser("redundancias"); s.add_argument("--limiar", type=float, default=cfg_padrao_limiar()); s.add_argument("--limite", type=int, default=40); s.set_defaults(fn=cmd_redundancias)
    s = sub.add_parser("cadeias"); s.add_argument("--so-quebradas", action="store_true"); s.add_argument("--so-completas", action="store_true"); s.add_argument("--limite", type=int, default=60); s.set_defaults(fn=cmd_cadeias)
    s = sub.add_parser("cobertura"); s.add_argument("--tabela", default=""); s.set_defaults(fn=cmd_cobertura)
    sub.add_parser("dimensoes", help="matriz tabela x dimensao de qualidade").set_defaults(fn=cmd_dimensoes)
    sub.add_parser("exportar-grafo", help="dados/grafo.gexf para Gephi/Cytoscape").set_defaults(fn=cmd_exportar_grafo)
    s = sub.add_parser("anotar", help="o agente registra o que leu, concluiu ou perguntou (trilha)"); s.add_argument("texto", nargs="?", default=""); s.add_argument("--leu", default="", help="ex.: skill:regras-cadflow, prompt:nova-regra, instructions"); s.add_argument("--pergunta", default=""); s.add_argument("--resposta", default=""); s.add_argument("--erro", default=""); s.set_defaults(fn=cmd_anotar)
    s = sub.add_parser("trilha", help="ver, zerar, exportar, ligar/desligar a trilha da conversa"); s.add_argument("--nova", default="", help="zera e inicia (texto = motivo; '-' = sem motivo)"); s.add_argument("--limpar", action="store_true"); s.add_argument("--exportar", action="store_true"); s.add_argument("--ligar", action="store_true"); s.add_argument("--desligar", action="store_true"); s.add_argument("--abrir", action="store_true"); s.add_argument("--limite", type=int, default=30); s.set_defaults(fn=cmd_trilha)
    s = sub.add_parser("desfazer", help="remove regras criadas pelo cdflw (registro, Excel e ficha) para refaze-las"); s.add_argument("codigos", nargs="*"); s.add_argument("--cadeia", action="store_true", help="inclui RN/filhas e encadeadas criadas pelo cdflw"); s.add_argument("--lote", default="", help="todas as regras gravadas na mesma rodada"); s.add_argument("--listar", action="store_true", help="so mostra o que seria removido"); s.add_argument("--manter-excel", action="store_true", help="nao mexe na planilha"); s.set_defaults(fn=cmd_desfazer)
    s = sub.add_parser("grafo-html", help="regera dados/grafo.html"); s.add_argument("--abrir", action="store_true", help="abre no navegador"); s.set_defaults(fn=cmd_grafo_html)
    a = ap.parse_args(argv)
    cfg = nucleo.carregar(Path(a.raiz) if a.raiz else None)
    global _ARQUIVO_SAIDA
    try:
        cfg.saida.mkdir(parents=True, exist_ok=True)
        _ARQUIVO_SAIDA = cfg.saida / "_ultimo_comando.txt"
        _ARQUIVO_SAIDA.write_text(f"$ cdflw {' '.join(argv if argv is not None else sys.argv[1:])}\n", encoding="utf-8", newline="\n")
    except OSError:
        _ARQUIVO_SAIDA = None
    try:
        rc = a.fn(cfg, a)
    except SystemExit as e:
        _p(str(e))
        raise
    if a.cmd not in ("anotar", "trilha", "instalar", "configurar", "atualizar", "recursos") and ativa(cfg):
        args = [x for x in (argv if argv is not None else sys.argv[1:]) if x != "--raiz" and not x.startswith("C:") and not x.startswith("/")]
        try:
            saida = _ARQUIVO_SAIDA.read_text(encoding="utf-8") if _ARQUIVO_SAIDA else ""
        except OSError:
            saida = ""
        registrar(cfg, "erro" if rc else "comando", " ".join(args)[:160], saida.split("\n", 1)[1] if "\n" in saida else saida, {"rc": rc})
    return rc


if __name__ == "__main__":
    sys.exit(main())
