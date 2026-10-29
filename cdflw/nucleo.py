"""cdflw: o nucleo (dominio das regras).

Texto e siglas, configuracao (config.toml + config.local.toml), leitura da base da Governanca,
codigos, mapa de tabelas, validador (C1..C20), gravacao (Excel, ficha, registro, desfazer) e
geracao das referencias da skill. Nenhuma funcao aqui chama LLM.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import shutil
import tomllib
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from typing import Any, Iterable



# ==========================================================================================
# md: Saneamento de texto para Markdown gerado.
# ==========================================================================================



_ESPACOS = re.compile(r"[ \t\f\v]+")
_QUEBRAS_3 = re.compile(r"\n{3,}")
# inicio de linha que o Markdown trata como bloco: titulo, item de lista, citacao, tabela, cerca, regua
_BLOCO = re.compile(r"^(\s{0,3})(#{1,6}\s|[-*+]\s|>|\||```|~~~|(?:-{3,}|\*{3,}|_{3,})\s*$|\d{1,9}[.)]\s)")


def quebras(texto: object) -> str:
    """Normaliza fim de linha (CRLF/CR -> LF), tira BOM e espacos no fim de cada linha."""
    t = "" if texto is None else str(texto)
    t = t.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(l.rstrip() for l in t.split("\n"))


def inline(texto: object) -> str:
    """Uma linha so: para item de lista, titulo ou qualquer lugar onde uma quebra mudaria a estrutura."""
    t = quebras(texto).strip()
    t = t.replace("\n", " ")
    return _ESPACOS.sub(" ", t).strip()


def celula(texto: object) -> str:
    """Conteudo de celula de tabela: uma linha, sem '|' solto."""
    return inline(texto).replace("|", "\\|")


def bloco(texto: object) -> str:
    """Paragrafos de um campo da ficha: mantem as quebras, mas nenhuma linha vira estrutura.

    Uma linha que comecaria um titulo, lista, tabela ou cerca ganha uma barra invertida no inicio,
    que o Markdown descarta ao renderizar e o Excel/CadFlow nunca veem (o texto da ficha vai
    para la a partir dos campos, nao deste arquivo).
    """
    t = quebras(texto).strip()
    t = _QUEBRAS_3.sub("\n\n", t)
    saida = []
    for l in t.split("\n"):
        m = _BLOCO.match(l)
        if m:
            l = l[: len(m.group(1))] + "\\" + l[len(m.group(1)):]
        saida.append(l)
    return "\n".join(saida)


def cerca(texto: object) -> list[str]:
    """Bloco de codigo cujo conteudo pode conter crases triplas: escolhe uma cerca que nao colide."""
    t = quebras(texto)
    marca = "```"
    while marca in t:
        marca += "`"
    return [marca, t, marca]


# ==========================================================================================
# texto: Funcoes de texto: encoding quebrado, normalizacao, extracao de siglas e codigos.
# ==========================================================================================



# Sinal classico de UTF-8 lido como cp1252: "Ã" ou "Â" seguido de outro byte alto.
_MOJIBAKE = re.compile(r"[ÃÂâ][\u0080-¿€-™ -ÿ]")


def corrigir_mojibake(texto: str, max_passos: int = 3) -> str:
    """Desfaz 'GeraÃ§Ã£o' -> 'Geração'. Idempotente em texto sao.

    Tenta a reversao inteira; se falhar, linha a linha, para nao perder um
    documento inteiro por causa de um caractere.
    """
    for _ in range(max_passos):
        if not _MOJIBAKE.search(texto):
            return texto
        try:
            texto = texto.encode("cp1252").decode("utf-8")
            continue
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        linhas = []
        mudou = False
        for linha in texto.splitlines(keepends=True):
            if _MOJIBAKE.search(linha):
                try:
                    linha2 = linha.encode("cp1252").decode("utf-8")
                    mudou = mudou or (linha2 != linha)
                    linha = linha2
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            linhas.append(linha)
        texto = "".join(linhas)
        if not mudou:
            return texto
    return texto


def ler_texto(caminho) -> str:
    """Le um arquivo como UTF-8 (com BOM ou nao), cai para cp1252, e corrige mojibake."""
    dados = open(caminho, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            texto = dados.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return corrigir_mojibake(texto).replace("\r\n", "\n")


def sem_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def normalizar(texto: str) -> str:
    """Minusculas, sem acentos, espacos colapsados. Para comparar, nunca para exibir."""
    return re.sub(r"\s+", " ", sem_acentos(texto or "").lower()).strip()


def limpar_nan(valor) -> str:
    """Exports via pandas deixam 'nan' literal. Vira vazio."""
    if valor is None:
        return ""
    s = str(valor).strip()
    return "" if s.lower() in ("nan", "none", "null") else s


# Sigla de campo: maiusculas/digitos com pelo menos um underscore (CMPO_VALOR_X),
# ou palavra em maiusculas de 3+ letras (CMPO_NAC, CUF) que sera filtrada por lista.
_SIGLA_COM_UNDERSCORE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_SIGLA_CURTA = re.compile(r"\b[A-Z]{3,}\b")

# Codigo de regra: PFX.TT.n ou PFX.RNk.TTn (ex.: ICT.RV.5, IBS.RN1.RE3, IBS.RN1)
CODIGO_RE = re.compile(r"\b([A-Z]{2,4})\.(R[A-Z])\.?(\d+)(?:\.(R[A-Z])\.?(\d+))?\b")


def siglas(texto: str, nao_siglas: set[str] | None = None) -> list[str]:
    """Siglas tecnicas citadas no texto, na ordem, sem repeticao.

    Codigos de regra (ICT.RV.1) sao removidos antes: o prefixo de 3 letras nao e campo.
    """
    nao = {s.upper() for s in (nao_siglas or set())}
    texto = CODIGO_RE.sub(" ", texto or "")
    vistas: list[str] = []
    for m in _SIGLA_COM_UNDERSCORE.finditer(texto or ""):
        s = m.group(0)
        if s not in vistas and s not in nao:
            vistas.append(s)
    for m in _SIGLA_CURTA.finditer(texto or ""):
        s = m.group(0)
        if s not in vistas and s not in nao and not any(s in v for v in vistas):
            vistas.append(s)
    return vistas


def dominios_citados(texto: str) -> list[str]:
    """Referencias de dominio no formato '(TABELA - CODIGO)'."""
    return [f"{a} - {b}" for a, b in re.findall(r"\(([A-Z][A-Z0-9_/]+)\s*-\s*([A-Z0-9]+)\)", texto or "")]


def codigos_citados(texto: str) -> list[str]:
    """Codigos de regra citados ('Executar regra ICT.RL.3', 'pela regra ICT.RV.5')."""
    achados: list[str] = []
    for m in CODIGO_RE.finditer(texto or ""):
        cod = normalizar_codigo(m.group(0))
        if cod not in achados:
            achados.append(cod)
    return achados


def normalizar_codigo(codigo: str) -> str:
    """'ICT.RV5' e 'ICT.RV.5' viram 'ICT.RV.5'; composto 'IBS.RN1.RE3' fica 'IBS.RN1.RE3'."""
    m = CODIGO_RE.search((codigo or "").strip().upper())
    if not m:
        return (codigo or "").strip().upper()
    pfx, t1, n1, t2, n2 = m.groups()
    if t2:
        return f"{pfx}.{t1}{n1}.{t2}{n2}"
    return f"{pfx}.{t1}.{n1}"


def decompor_codigo(codigo: str) -> dict[str, str]:
    """{'prefixo','tipo','numero','rn'} de um codigo simples ou composto."""
    m = CODIGO_RE.search((codigo or "").strip().upper())
    if not m:
        return {}
    pfx, t1, n1, t2, n2 = m.groups()
    if t2:
        return {"prefixo": pfx, "tipo": t2, "numero": n2, "rn": f"{pfx}.{t1}.{n1}"}
    return {"prefixo": pfx, "tipo": t1, "numero": n1, "rn": ""}


def primeira_palavra(texto: str) -> str:
    m = re.search(r"[A-Za-zÀ-ÿ]+", texto or "")
    return m.group(0).lower() if m else ""


def tabela_e_sigla(texto: str) -> tuple[str, str]:
    """'Informações de Contato (INFO_CNTTO)' -> ('Informações Pessoa Física', 'INFO_CNTTO')."""
    m = re.match(r"\s*(.*?)\s*\(([A-Z][A-Z0-9_]+)\)\s*$", texto or "")
    if m:
        return m.group(1).strip(), m.group(2)
    t = (texto or "").strip()
    return (t, t) if re.fullmatch(r"[A-Z][A-Z0-9_]+", t) else (t, "")


# Nome totalmente qualificado do Unity Catalog: catalogo.schema.tabela (minusculas, com ou sem crases).
_FQN_RE = re.compile(r"`?([a-z][a-z0-9_]*)`?\.`?([a-z][a-z0-9_]*)`?\.`?([a-z][a-z0-9_]*)`?")


def tabelas_qualificadas(texto: str) -> list[str]:
    """'cat.schema.tabela' citados no texto, sem repeticao. Codigos de regra (ICT.RV.3) nao casam."""
    achados: list[str] = []
    for m in _FQN_RE.finditer(texto or ""):
        fqn = ".".join(m.groups())
        if fqn not in achados:
            achados.append(fqn)
    return achados


# ==========================================================================================
# config: Leitura do config.toml e resolucao de caminhos.
# ==========================================================================================



RAIZ_PROJETO = Path(__file__).resolve().parent  # a pasta cdflw/ (codigo + config.toml + base/dados/saida)


@dataclass
class Config:
    raiz: Path
    bruto: dict[str, Any] = field(default_factory=dict)

    # --- secoes ---------------------------------------------------------
    @property
    def databricks(self) -> dict[str, Any]:
        return self.bruto.get("databricks", {})

    @property
    def regras(self) -> dict[str, Any]:
        return self.bruto.get("regras", {})

    @property
    def copilot(self) -> dict[str, Any]:
        return self.bruto.get("copilot", {})

    @property
    def excel(self) -> dict[str, Any]:
        return self.bruto.get("excel", {})

    @property
    def mapa_tabelas(self) -> dict[str, Any]:
        return self.bruto.get("mapa_tabelas", {})

    # --- caminhos -------------------------------------------------------
    def caminho(self, chave: str, padrao: str) -> Path:
        valor = self.bruto.get("caminhos", {}).get(chave, padrao)
        p = Path(valor)
        return p if p.is_absolute() else (self.raiz / p).resolve()

    @property
    def base(self) -> Path:
        return self.caminho("base", "base")

    @property
    def dados(self) -> Path:
        return self.caminho("dados", "dados")

    @property
    def saida(self) -> Path:
        return self.caminho("saida", "saida")

    @property
    def excel_saida(self) -> Path:
        return self.caminho("excel", "saida/regras_novas.xlsx")

    @property
    def fichas(self) -> Path:
        return self.caminho("fichas", "saida/fichas")

    @property
    def raiz_workspace(self) -> Path:
        """A raiz do repositorio (a pasta que o VS Code abre): e onde ficam .github, .vscode e .databricks."""
        return self.caminho("raiz_workspace", "..")

    @property
    def copilot_fonte(self) -> Path:
        """O unico .github: o da raiz do repositorio. E o que o Copilot le; as referencias sao geradas nele."""
        return self.raiz_workspace / ".github"

    # --- databricks -----------------------------------------------------
    def _project_json(self) -> dict[str, Any]:
        """A extensao Databricks grava profile e cluster em .databricks/project.json."""
        for candidato in (self.raiz_workspace / ".databricks" / "project.json",
                          self.raiz / ".databricks" / "project.json"):
            if candidato.exists():
                try:
                    return json.loads(candidato.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return {}
        return {}

    @property
    def profile(self) -> str:
        return self.databricks.get("profile") or self._project_json().get("profile", "") or "DEFAULT"

    @property
    def cluster_id(self) -> str:
        pj = self._project_json()
        return self.databricks.get("cluster_id") or pj.get("clusterId", "") or pj.get("cluster_id", "")

    @property
    def warehouse_id(self) -> str:
        return self.databricks.get("warehouse_id", "")

    @property
    def catalogo(self) -> str:
        return self.databricks.get("catalogo", "")

    @property
    def schema(self) -> str:
        return self.databricks.get("schema", "")

    @property
    def quer_linhagem(self) -> bool:
        return bool(self.databricks.get("linhagem", True))

    @property
    def auto_ligar_cluster(self) -> bool:
        return bool(self.databricks.get("auto_ligar_cluster", True))

    @property
    def espera_cluster_s(self) -> int:
        return int(self.databricks.get("espera_cluster_s", 240))

    @property
    def intervalo_poll_s(self) -> int:
        return int(self.databricks.get("intervalo_poll_s", 15))

    @property
    def schemas_preferidos(self) -> list[str]:
        return list(self.databricks.get("schemas_preferidos", []))

    @property
    def schemas_busca(self) -> list[str]:
        return list(self.databricks.get("schemas_busca", []))

    @property
    def usar_query_history(self) -> bool:
        return bool(self.databricks.get("usar_query_history", True))

    @property
    def dias_uso(self) -> int:
        return int(self.databricks.get("dias_uso", 30))

    @property
    def max_linhas_sem_amostra(self) -> int:
        return int(self.databricks.get("max_linhas_sem_amostra", 5_000_000))

    @property
    def max_valores_frequentes(self) -> int:
        return int(self.databricks.get("max_valores_frequentes", 10))

    @property
    def mascarar_amostras(self) -> bool:
        return bool(self.databricks.get("mascarar_amostras", True))

    @property
    def limiar_redundancia(self) -> float:
        return float(self.bruto.get("analise", {}).get("limiar_redundancia", 0.6))

    # --- regras ---------------------------------------------------------
    @property
    def tipos(self) -> list[str]:
        return list(self.regras.get("tipos", []))

    @property
    def criticidades(self) -> list[str]:
        return list(self.regras.get("criticidades", []))

    @property
    def tipos_pessoa(self) -> list[str]:
        return list(self.regras.get("tipos_pessoa", []))

    @property
    def sufixo_tipo(self) -> dict[str, str]:
        return dict(self.regras.get("sufixo_tipo", {}))

    @property
    def verbos(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self.regras.get("verbos", {}).items()}

    @property
    def fatos_dominio(self) -> list[str]:
        return list(self.regras.get("fatos_dominio", []))

    @property
    def objetivo_proibido(self) -> list[str]:
        return list(self.regras.get("objetivo_proibido", []))

    @property
    def nao_siglas(self) -> set[str]:
        return set(self.regras.get("nao_siglas", []))

    @property
    def prefixos(self) -> dict[str, str]:
        return dict(self.mapa_tabelas.get("prefixo", {}))

    @property
    def mapa_uc(self) -> dict[str, str]:
        return dict(self.mapa_tabelas.get("uc", {}))

    @property
    def colunas_excel(self) -> list[str]:
        return list(self.excel.get("colunas", []))

    @property
    def regras_encadeadas_na_planilha(self) -> bool:
        """false (padrao): a coluna regras_encadeadas sai vazia; o vinculo fica so no registro interno."""
        return bool(self.excel.get("regras_encadeadas_na_planilha", False))

    @property
    def modelo(self) -> str:
        return self.copilot.get("modelo", "")


def gravar_valor(raiz: Path, secao: str, chave: str, valor: str, arquivo: str = "config.toml") -> None:
    """Troca `chave = "..."` dentro de [secao] no config.toml (ou config.local.toml), preservando
    comentarios e ordem.

    Edicao por linha, de proposito: tomllib nao escreve, e reescrever o arquivo inteiro
    apagaria os comentarios que explicam cada opcao ao usuario.
    """
    import re

    arquivo_p = raiz / arquivo
    if not arquivo_p.exists():
        arquivo_p.write_text("# Valores desta maquina/pessoa. Sobrepoe o config.toml da equipe. Nao vai para o git.\n", encoding="utf-8", newline="\n")
    linhas = arquivo_p.read_text(encoding="utf-8").split("\n")
    em_secao = False
    feito = False
    for i, l in enumerate(linhas):
        m = re.match(r"\s*\[([^\]]+)\]\s*$", l)
        if m:
            em_secao = m.group(1).strip() == secao
            continue
        if em_secao and re.match(rf"\s*{re.escape(chave)}\s*=", l):
            linhas[i] = f'{chave} = "{valor}"'
            feito = True
            break
    if not feito:
        # secao inexistente ou chave ausente: acrescenta no fim da secao (ou cria a secao)
        # procura a secao como linha propria: "# [mapa_tabelas.prefixo]" comentada nao conta
        if not any(l.strip() == f"[{secao}]" for l in linhas):
            linhas += ["", f"[{secao}]"]
        idx = next(i for i, l in enumerate(linhas) if l.strip() == f"[{secao}]")
        fim = idx + 1
        while fim < len(linhas) and not linhas[fim].strip().startswith("["):
            fim += 1
        linhas.insert(fim, f'{chave} = "{valor}"')
    arquivo_p.write_text("\n".join(linhas), encoding="utf-8", newline="\n")


def carregar(raiz: Path | None = None) -> Config:
    raiz = (raiz or RAIZ_PROJETO).resolve()
    arquivo = raiz / "config.toml"
    if not arquivo.exists():
        raise SystemExit(f"config.toml nao encontrado em {raiz}. Ele fica na pasta cdflw/, ao lado do codigo.")
    with arquivo.open("rb") as f:
        bruto = tomllib.load(f)
    # config.local.toml: valores da pessoa/maquina (profile, cluster) por cima dos da equipe
    local = raiz / "config.local.toml"
    if local.exists():
        with local.open("rb") as f:
            extra = tomllib.load(f)
        for secao, valores in extra.items():
            if isinstance(valores, dict) and isinstance(bruto.get(secao), dict):
                for k, v in valores.items():
                    if isinstance(v, dict) and isinstance(bruto[secao].get(k), dict):
                        bruto[secao][k].update(v)
                    else:
                        bruto[secao][k] = v
            else:
                bruto[secao] = valores
    return Config(raiz=raiz, bruto=bruto)


# ==========================================================================================
# base: Leitura da pasta base/: base de conhecimento, regras aprovadas (md) e export do CadFlow (xlsx).
# ==========================================================================================




CAMPOS_REGRA = [
    "codigo", "codigo_comp", "rn", "nome", "tipo", "criticidade", "tabela", "tabela_sigla",
    "tipo_pessoa", "descricao", "objetivo", "criterio_aplicacao", "logica_execucao", "resultado",
    "exemplo", "acao_dado_valido", "acao_dado_invalido", "regras_encadeadas", "codigos_regra_geral",
    "observacao", "pontos_atencao", "metrica_monitoramento", "status", "flags", "origem", "campos", "dominios", "extras",
]

# nome normalizado do campo (md ou cabecalho xlsx) -> chave interna
_SINONIMOS: dict[str, str] = {
    "codigo": "codigo", "codigo regra": "codigo", "codigo da regra": "codigo",
    "codigo regra comp": "codigo_comp", "codgo regra comp": "codigo_comp", "codigo composto": "codigo_comp",
    "nome": "nome", "nome regra": "nome", "regra": "nome", "title": "titulo",
    "tipo": "tipo", "tipo regra": "tipo", "tipo da regra": "tipo",
    "criticidade": "criticidade",
    "tabela": "tabela", "tabela dados": "tabela", "tabela de dados": "tabela", "sigla tabela": "tabela",
    "tipo pessoa": "tipo_pessoa", "tipo pessoa afetada": "tipo_pessoa",
    "descricao": "descricao", "descricao regra": "descricao",
    "objetivo": "objetivo", "objetivo regra": "objetivo",
    "criterio de aplicacao": "criterio_aplicacao", "criterio aplicacao": "criterio_aplicacao",
    "logica de execucao": "logica_execucao", "logica execucao": "logica_execucao",
    "resultado": "resultado", "resultado esperado": "resultado",
    "exemplo": "exemplo",
    "acao dado valido": "acao_dado_valido", "acao para dado valido": "acao_dado_valido",
    "acao dado invalido": "acao_dado_invalido", "acao para dado invalido": "acao_dado_invalido",
    "codigos regra geral": "codigos_regra_geral", "regra geral": "codigos_regra_geral",
    "observacao": "observacao", "observacoes": "observacao", "pontos de atencao": "pontos_atencao", "ponto de atencao": "pontos_atencao",
    "metrica monitoramento": "metrica_monitoramento",
    "status": "status", "id": "id",
}

_FLAGS = ("is_legacy", "is_backlog", "is_editing")


def regra_vazia() -> dict[str, Any]:
    r: dict[str, Any] = {c: "" for c in CAMPOS_REGRA}
    r["regras_encadeadas"] = []
    r["campos"] = []
    r["dominios"] = []
    r["flags"] = {}
    r["extras"] = {}
    return r


def _chave(nome_campo: str) -> str:
    n = normalizar(nome_campo).replace("_", " ").replace(":", "").strip()
    if n in _SINONIMOS:
        return _SINONIMOS[n]
    # 'descricao_<bloco>' do export do CadFlow
    if n.startswith("descricao ") and n != "descricao regra":
        return "bloco"
    for k, v in _SINONIMOS.items():
        if n == k:
            return v
    return ""


def completar(regra: dict[str, Any], nao_siglas: set[str] | None = None) -> dict[str, Any]:
    """Preenche os campos derivados (sigla da tabela, codigos, siglas, dominios)."""
    if regra.get("tabela") and not regra.get("tabela_sigla"):
        nome, sigla = tabela_e_sigla(regra["tabela"])
        regra["tabela"], regra["tabela_sigla"] = nome, sigla
    if regra.get("codigo"):
        regra["codigo"] = normalizar_codigo(regra["codigo"])
    if regra.get("codigo_comp"):
        regra["codigo_comp"] = normalizar_codigo(regra["codigo_comp"])
        m = re.match(r"([A-Z]{2,4})\.(RN\d+)\.", regra["codigo_comp"])
        if m and not regra.get("rn"):
            regra["rn"] = normalizar_codigo(f"{m.group(1)}.{m.group(2)}")
    texto_acoes = " ".join(str(regra.get(c, "")) for c in ("acao_dado_valido", "acao_dado_invalido", "resultado", "logica_execucao", "criterio_aplicacao"))
    citados = [c for c in codigos_citados(texto_acoes) if c != regra.get("codigo")]
    # `familia`: vinculo tecnico informado pelo agente (codigos criados juntos), que nunca aparece no
    # texto da regra. Entra em regras_encadeadas para o grafo e o desfazer --cadeia enxergarem.
    familia = regra.get("familia") or []
    if isinstance(familia, str):
        familia = [c for c in re.split(r"[,; ]+", familia) if c]
    for c in familia:
        c = normalizar_codigo(c)
        if c and c != regra.get("codigo") and c not in citados:
            citados.append(c)
    regra["regras_encadeadas"] = citados
    texto_logico = " ".join(str(regra.get(c, "")) for c in ("logica_execucao", "criterio_aplicacao", "exemplo"))
    regra["campos"] = [s for s in siglas(texto_logico, nao_siglas) if s != regra.get("tabela_sigla")]
    regra["dominios"] = dominios_citados(texto_logico)
    regra["tabelas_citadas"] = tabelas_qualificadas(texto_logico)
    return regra


# ---------------------------------------------------------------------------
# Regras aprovadas em Markdown (formato gerado pela Governanca)
# ---------------------------------------------------------------------------
_INICIO_REGRA = re.compile(r"^\s*#*\s*\**\s*Regra\s*:\s*(.+?)\s*\**\s*$")
_CAMPO_MD = re.compile(r"^\s*(?:[-*]\s*)?\**\s*([A-Za-zÀ-ÿ ]{3,40}?)\s*\**\s*:\**\s*(.*)$")


def ler_aprovadas_md(caminho: Path, nao_siglas: set[str] | None = None) -> list[dict[str, Any]]:
    texto = ler_texto(caminho)
    regras: list[dict[str, Any]] = []
    atual: dict[str, Any] | None = None
    ultimo_campo = ""
    for linha in texto.split("\n"):
        m = _INICIO_REGRA.match(linha)
        if m:
            if atual:
                regras.append(completar(atual, nao_siglas))
            atual = regra_vazia()
            atual["nome"] = m.group(1).strip().strip("*")
            atual["origem"] = "aprovadas_md"
            atual["status"] = "Aprovada"
            ultimo_campo = ""
            continue
        if atual is None:
            continue
        if linha.strip() in ("", "---"):
            continue
        m = _CAMPO_MD.match(linha)
        chave = _chave(m.group(1)) if m else ""
        if m and chave:
            valor = limpar_nan(m.group(2).strip())
            if chave in atual and isinstance(atual[chave], str):
                atual[chave] = valor
            else:
                atual["extras"][chave] = valor
            ultimo_campo = chave
            continue
        # linha de continuacao do campo anterior (paragrafos soltos abaixo da lista)
        if ultimo_campo and ultimo_campo in atual and isinstance(atual[ultimo_campo], str):
            atual[ultimo_campo] = (atual[ultimo_campo] + "\n" + linha.strip()).strip()
    if atual:
        regras.append(completar(atual, nao_siglas))
    return regras


# ---------------------------------------------------------------------------
# Export do CadFlow em xlsx (lista do SharePoint)
# ---------------------------------------------------------------------------
def ler_export_xlsx(caminho: Path, nao_siglas: set[str] | None = None) -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    wb = load_workbook(caminho, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    linhas = ws.iter_rows(values_only=True)
    cabecalho = [str(c or "").strip() for c in next(linhas)]
    chaves = [_chave(c) for c in cabecalho]
    regras: list[dict[str, Any]] = []
    for valores in linhas:
        if not any(v not in (None, "") for v in valores):
            continue
        r = regra_vazia()
        r["origem"] = "export_xlsx"
        for nome_col, chave, valor in zip(cabecalho, chaves, valores):
            v = limpar_nan(valor)
            nc = normalizar(nome_col).replace(" ", "_")
            if nc in _FLAGS:
                r["flags"][nc] = str(valor).strip().upper() in ("VERDADEIRO", "TRUE", "1", "SIM")
            elif chave and chave in r and isinstance(r[chave], str):
                r[chave] = v
            elif chave == "bloco":
                r["extras"]["bloco"] = v
            elif v:
                r["extras"][nome_col] = v
        if not r["status"]:
            r["status"] = "Aprovada" if r["extras"].get("status_aprovacao") else ""
        regras.append(completar(r, nao_siglas))
    wb.close()
    return regras


# ---------------------------------------------------------------------------
# Base de conhecimento (Markdown com JSON por conceito)
# ---------------------------------------------------------------------------
def _objetos_json(texto: str) -> list[Any]:
    """Todos os objetos/arrays JSON do texto, dentro ou fora de cercas de codigo."""
    decoder = json.JSONDecoder()
    achados: list[Any] = []
    i = 0
    n = len(texto)
    while i < n:
        c = texto[i]
        if c in "[{":
            try:
                obj, fim = decoder.raw_decode(texto, i)
                achados.append(obj)
                i = fim
                continue
            except json.JSONDecodeError:
                pass
        i += 1
    return achados


def ler_base_conhecimento(caminho: Path) -> dict[str, Any]:
    texto = ler_texto(caminho)
    por_secao: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in _objetos_json(texto):
        itens = obj if isinstance(obj, list) else [obj]
        for item in itens:
            if isinstance(item, dict) and "secao" in item:
                por_secao[str(item["secao"])].append(item)
    # texto sem a secao de chunking (so interessa a quem faz RAG)
    limpo = re.sub(r"(?is)^#+\s*par[aâ]metros de chunking.*?(?=^#+ )", "", texto, flags=re.M)
    return {"secoes": dict(por_secao), "texto": limpo.strip()}


def tipos_da_base(kb: dict[str, Any]) -> list[str]:
    return [str(t.get("tipo")) for t in kb.get("secoes", {}).get("tipos_de_regra", []) if t.get("tipo")]


def campos_obrigatorios_da_base(kb: dict[str, Any]) -> dict[str, list[str]]:
    """{'TODAS': [...], 'Validação': [...]} a partir da secao campos_obrigatorios."""
    saida: dict[str, list[str]] = defaultdict(list)
    for item in kb.get("secoes", {}).get("campos_obrigatorios", []):
        if not item.get("obrigatorio", True):
            continue
        aplic = str(item.get("aplicavel_a", "TODAS"))
        alvo = "TODAS" if "todas" in normalizar(aplic) else re.sub(r"(?i)^apenas regras do tipo\s*", "", aplic).strip()
        saida[alvo].append(str(item.get("campo", "")))
    return dict(saida)


# ---------------------------------------------------------------------------
# Glossario sigla <-> termo de negocio, extraido das aprovadas
# ---------------------------------------------------------------------------
_TERMO = re.compile(r"campos?\s+(?:de\s+|do\s+|da\s+)?([a-zà-ÿ][a-zà-ÿ ]{2,60}?)(?=[,.;:()]|\s+(?:de uma|da pessoa|do cliente|no PSDC|na |em |quando|pois|por |para |e |ou |se |que |est[aá]|nos |com )|$)", re.I)
_SIGLA_CAMPO = re.compile(r"campos?\s+([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[A-Z]{3,})\b")


def extrair_glossario(regras: list[dict[str, Any]], comentarios_uc: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Pareia 'campo <termo>' da Descricao com 'campo <SIGLA>' da Logica, regra a regra."""
    votos: dict[str, Counter] = defaultdict(Counter)
    tabela_de: dict[str, str] = {}
    fonte: dict[str, str] = {}
    for r in regras:
        siglas_logica = [s for s in _SIGLA_CAMPO.findall(r.get("logica_execucao", "")) if s != r.get("tabela_sigla")]
        termos = [t.strip() for t in _TERMO.findall(" ".join((r.get("descricao", ""), r.get("objetivo", ""), r.get("criterio_aplicacao", ""))))]
        termos = [t for t in termos if not re.search(r"[A-Z0-9]+_[A-Z0-9]+", t)]
        # mesmo termo repetido em descricao e criterio conta uma vez
        termos = list(dict.fromkeys(termos))
        if not siglas_logica:
            continue
        if len(siglas_logica) == 1 and termos:
            votos[siglas_logica[0]][termos[0]] += 2
        elif len(siglas_logica) == len(termos):
            for s, t in zip(siglas_logica, termos):
                votos[s][t] += 1
        for s in siglas_logica:
            tabela_de.setdefault(s, r.get("tabela_sigla", ""))
            fonte.setdefault(s, r.get("codigo") or r.get("nome", ""))
    saida: list[dict[str, str]] = []
    for s, c in votos.items():
        termo, peso = c.most_common(1)[0]
        saida.append({"sigla": s, "termo_negocio": termo, "tabela_sigla": tabela_de.get(s, ""),
                      "fonte": fonte.get(s, ""), "confianca": "alta" if peso >= 2 else "media"})
    for s, com in (comentarios_uc or {}).items():
        if com and s.upper() not in votos:
            saida.append({"sigla": s.upper(), "termo_negocio": com, "tabela_sigla": "", "fonte": "unity_catalog", "confianca": "alta"})
    return sorted(saida, key=lambda x: x["sigla"])


# ---------------------------------------------------------------------------
# Persistencia simples
# ---------------------------------------------------------------------------
def gravar_jsonl(caminho: Path, itens: list[dict[str, Any]]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8", newline="\n") as f:
        for it in itens:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def ler_jsonl(caminho: Path) -> list[dict[str, Any]]:
    if not caminho.exists():
        return []
    with caminho.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def gravar_glossario_csv(caminho: Path, itens: list[dict[str, str]]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sigla", "termo_negocio", "tabela_sigla", "fonte", "confianca"], delimiter=";")
        w.writeheader()
        w.writerows(itens)


def ler_glossario_csv(caminho: Path) -> list[dict[str, str]]:
    if not caminho.exists():
        return []
    with caminho.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def descobrir_arquivos(base: Path) -> dict[str, list[Path]]:
    """Que arquivos existem em base/: conhecimento (md), aprovadas (md), export (xlsx)."""
    achados: dict[str, list[Path]] = {"conhecimento": [], "aprovadas": [], "export": []}
    if not base.exists():
        return achados
    for p in sorted(base.iterdir()):
        n = normalizar(p.name)
        if p.suffix.lower() == ".xlsx" and not p.name.startswith("~$"):
            achados["export"].append(p)
        elif p.suffix.lower() == ".md":
            if "governanca" in n or "conhecimento" in n:
                achados["conhecimento"].append(p)
            elif "aprovad" in n or "regras" in n:
                achados["aprovadas"].append(p)
    return achados


# ==========================================================================================
# codigo: Proximo codigo livre no padrao PFX.TT.n (e composto PFX.RNk.TTn).
# ==========================================================================================





def codigos_usados(regras: Iterable[dict[str, Any]]) -> set[str]:
    usados: set[str] = set()
    for r in regras:
        for c in (r.get("codigo"), r.get("codigo_comp"), r.get("rn")):
            if c:
                usados.add(normalizar_codigo(c))
        for c in r.get("regras_encadeadas", []):
            usados.add(normalizar_codigo(c))
    return usados


def proximo(prefixo: str, tipo: str, cfg: Config, usados: set[str], rn: str = "") -> dict[str, str]:
    """{'codigo': 'ICT.RV.8', 'codigo_comp': 'ICT.RN1.RV8'} (composto so se houver RN)."""
    suf = cfg.sufixo_tipo.get(tipo)
    if not suf:
        raise ValueError(f"tipo '{tipo}' sem sufixo configurado em [regras].sufixo_tipo")
    prefixo = prefixo.strip().upper()
    maior = 0
    padrao = re.compile(rf"^{re.escape(prefixo)}\.(?:RN\d+\.)?{suf}\.?(\d+)$")
    for c in usados:
        m = padrao.match(c)
        if m:
            maior = max(maior, int(m.group(1)))
        d = decompor_codigo(c)
        if d.get("prefixo") == prefixo and d.get("tipo") == suf:
            maior = max(maior, int(d["numero"]))
    n = maior + 1
    saida = {"codigo": f"{prefixo}.{suf}.{n}", "codigo_comp": ""}
    if rn:
        d = decompor_codigo(rn)
        if d and d.get("tipo") == "RN" and d.get("prefixo") == prefixo:
            saida["codigo_comp"] = f"{prefixo}.RN{d['numero']}.{suf}{n}"
        else:
            saida["aviso"] = f"RN '{rn}' nao e uma regra de negocio do prefixo {prefixo}"
    return saida


# ==========================================================================================
# mapa: Mapa entre o mundo do CadFlow (sigla de tabela, prefixo de codigo) e o Unity Catalog.
# ==========================================================================================





def inferir_prefixos(regras: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Sigla de tabela -> prefixo mais frequente nos codigos das regras dessa tabela."""
    votos: dict[str, Counter] = defaultdict(Counter)
    for r in regras:
        sig = r.get("tabela_sigla")
        d = decompor_codigo(r.get("codigo") or r.get("codigo_comp") or "")
        if sig and d.get("prefixo"):
            votos[sig][d["prefixo"]] += 1
        # regras encadeadas da mesma tabela tambem votam
        for c in r.get("regras_encadeadas", []):
            d2 = decompor_codigo(c)
            if sig and d2.get("prefixo"):
                votos[sig][d2["prefixo"]] += 0.5
    saida = {}
    for sig, c in votos.items():
        pfx, peso = c.most_common(1)[0]
        saida[sig] = {"prefixo": pfx, "votos": peso, "alternativas": [p for p, _ in c.most_common()[1:4]]}
    return saida


def inferir_tabelas_uc(regras: list[dict[str, Any]], snap: dict[str, Any], minimo: int = 2) -> dict[str, dict[str, Any]]:
    """Sigla de tabela CadFlow -> tabela UC com maior intersecao de colunas citadas."""
    campos_por_sigla: dict[str, set[str]] = defaultdict(set)
    for r in regras:
        if r.get("tabela_sigla"):
            campos_por_sigla[r["tabela_sigla"]].update(c.lower() for c in r.get("campos", []))
    colunas_uc = {nome: {c["nome"].lower() for c in t.get("colunas", [])} for nome, t in (snap.get("tabelas") or {}).items()}
    saida: dict[str, dict[str, Any]] = {}
    for sig, campos in campos_por_sigla.items():
        pontuacao = []
        for tab, cols in colunas_uc.items():
            inter = campos & cols
            if len(inter) >= minimo:
                pontuacao.append((len(inter), len(inter) / max(1, len(campos)), tab, sorted(inter)))
        pontuacao.sort(reverse=True)
        # segundo criterio: o nome da tabela UC contem a sigla (basico_x -> BASICO_X, basico_x_hive...)
        por_nome = _candidatas_por_nome(sig, list(colunas_uc))
        if pontuacao:
            n, frac, tab, inter = pontuacao[0]
            # entre empatados por colunas, prefere o nome mais curto (sem _hive/_previa/_bckp)
            empatados = [p for p in pontuacao if p[0] == n]
            if len(empatados) > 1:
                empatados.sort(key=lambda p: (len(p[2]), p[2]))
                n, frac, tab, inter = empatados[0]
            alternativas = [p[2] for p in pontuacao if p[2] != tab][:4]
            alternativas += [t for t in por_nome if t != tab and t not in alternativas][:2]
            saida[sig] = {"tabela_uc": tab, "campos_em_comum": n, "cobertura": round(frac, 2),
                          "exemplos": inter[:6], "alternativas": alternativas, "campos_citados": len(campos)}
        elif por_nome:
            saida[sig] = {"tabela_uc": por_nome[0], "campos_em_comum": 0, "cobertura": 0.0, "exemplos": [],
                          "alternativas": por_nome[1:4], "campos_citados": len(campos), "criterio": "nome"}
        else:
            saida[sig] = {"tabela_uc": "", "campos_em_comum": 0, "cobertura": 0.0, "exemplos": [],
                          "alternativas": [], "campos_citados": len(campos)}
    return saida


def _candidatas_por_nome(sigla: str, tabelas: list[str]) -> list[str]:
    """Tabelas cujo nome contem a sigla (ou a sigla sem o prefixo T de 'tabela'), nome mais curto primeiro."""
    s = sigla.lower()
    chaves = {s}
    if s.startswith("t") and len(s) > 4:
        chaves.add(s[1:])  # TDOCTO_PSSOA_UNIC -> docto_pssoa_unic
    achadas = [t for t in tabelas if any(k in t.lower() for k in chaves)]
    achadas.sort(key=lambda t: (len(t), t))
    return achadas


def mapa_final(cfg: Config, regras: list[dict[str, Any]], snap: dict[str, Any]) -> dict[str, Any]:
    """Junta inferencia + config. Marca o que esta confirmado (config) e o que e sugestao."""
    pfx_inf = inferir_prefixos(regras)
    uc_inf = inferir_tabelas_uc(regras, snap) if snap else {}
    siglas = set(pfx_inf) | set(uc_inf) | set(cfg.prefixos) | set(cfg.mapa_uc)
    saida: dict[str, Any] = {}
    for sig in sorted(siglas):
        saida[sig] = {
            "prefixo": cfg.prefixos.get(sig) or pfx_inf.get(sig, {}).get("prefixo", ""),
            "prefixo_confirmado": sig in cfg.prefixos,
            "prefixo_alternativas": pfx_inf.get(sig, {}).get("alternativas", []),
            "tabela_uc": cfg.mapa_uc.get(sig) or uc_inf.get(sig, {}).get("tabela_uc", ""),
            "tabela_uc_confirmada": sig in cfg.mapa_uc,
            "tabela_uc_cobertura": uc_inf.get(sig, {}).get("cobertura", 0.0),
            "tabela_uc_alternativas": uc_inf.get(sig, {}).get("alternativas", []),
            "tabela_uc_criterio": uc_inf.get(sig, {}).get("criterio", "colunas"),
        }
    return saida


def texto_mapa(mapa: dict[str, Any]) -> str:
    """Tabela em Markdown para o relatorio do /atualizar e para o usuario confirmar."""
    linhas = ["| Sigla CadFlow | Prefixo | Tabela UC | Cobertura | Confirmado |", "|---|---|---|---|---|"]
    for sig, m in mapa.items():
        conf = ("prefixo " if m["prefixo_confirmado"] else "") + ("uc" if m["tabela_uc_confirmada"] else "")
        alt = f" (ou {', '.join(m['tabela_uc_alternativas'])})" if m["tabela_uc_alternativas"] and not m["tabela_uc_confirmada"] else ""
        linhas.append("| " + " | ".join(celula(x) for x in (sig, m['prefixo'] or '?', f"{m['tabela_uc'] or '?'}{alt}", f"{m['tabela_uc_cobertura']:.0%}", conf.strip() or 'nao')) + " |")
    linhas.append("")
    linhas.append("Quando houver variantes (_hive, _previa, _bckp, sem sufixo), escolha a tabela que a Governanca considera oficial;")
    linhas.append("a sugestao e so a que mais compartilha colunas com as regras. Confira com: python -m cdflw tabela <nome>")
    linhas.append("")
    linhas.append("Para confirmar, copie no config.toml:")
    linhas.append("")
    linhas.append("[mapa_tabelas.prefixo]")
    for sig, m in mapa.items():
        if m["prefixo"]:
            linhas.append(f'{sig} = "{m["prefixo"]}"')
    linhas.append("")
    linhas.append("[mapa_tabelas.uc]")
    for sig, m in mapa.items():
        if m["tabela_uc"]:
            linhas.append(f'{sig} = "{m["tabela_uc"]}"')
    return "\n".join(linhas)


# ==========================================================================================
# validar: As verificacoes deterministicas de uma regra no padrao CadFlow.
# ==========================================================================================





@dataclass
class Achado:
    check: str
    nivel: str  # 'erro' | 'aviso'
    mensagem: str

    def __str__(self) -> str:
        return f"[{self.nivel.upper()}] {self.check}: {self.mensagem}"


@dataclass
class Contexto:
    """O que o validador sabe alem do config: o mundo em volta da regra."""
    siglas_conhecidas: set[str]            # colunas do UC + glossario (maiusculas)
    codigos_existentes: set[str]           # regras ja existentes (aprovadas + rascunhos)
    campos_obrigatorios: dict[str, list[str]] | None = None  # da base de conhecimento
    pedido: str = ""                       # texto livre do usuario, para checar fatos preservados
    codigos_em_criacao: set[str] | None = None  # regras criadas junto nesta conversa
    tabelas_conhecidas: set[str] | None = None  # nomes qualificados e simples do catalogo (snapshot + extras + mapa)
    nova: bool = False                     # True: regra em criacao (estilo vigente vira erro); False: calibracao de aprovadas


_CAMPOS_TEXTO = ("descricao", "objetivo", "criterio_aplicacao", "logica_execucao", "resultado", "exemplo",
                 "acao_dado_valido", "acao_dado_invalido", "observacao", "pontos_atencao")
# campos onde sigla de campo/tabela e permitida (4 Tabela, 8 Criterio, 9 Logica); nos demais e estilo
_CAMPOS_SEM_SIGLA_ESTILO = ("resultado", "exemplo", "acao_dado_valido", "acao_dado_invalido", "observacao", "pontos_atencao")
_MARCADOR = re.compile(r"<[A-Za-zÀ-ÿ][^<>\n]{1,60}>")
_ROTULO_RESULTADO = re.compile(r"\b(sucesso|falha|valido|invalido)\s*:")
_ACAO_VALIDA_VAGA = {"manter dado", "manter o dado", "manter", "mantem o dado", "mantem dado"}


_OBRIGATORIOS_TODAS = ["nome", "tipo", "criticidade", "tabela", "tipo_pessoa", "descricao", "objetivo",
                       "criterio_aplicacao", "logica_execucao", "resultado"]
_OBRIGATORIOS_VALIDACAO = ["exemplo", "acao_dado_valido", "acao_dado_invalido"]


def _canon(valor: str, opcoes: list[str]) -> str:
    """Devolve a grafia canonica de uma opcao (com acento) a partir de qualquer grafia."""
    n = normalizar(valor).replace(" ", "")
    for o in opcoes:
        if normalizar(o).replace(" ", "") == n:
            return o
    return ""


def canonizar(regra: dict[str, Any], cfg: Config) -> dict[str, Any]:
    """Normaliza grafias (tipo, criticidade, tipo pessoa, tabela) sem mudar o conteudo."""
    r = dict(regra)
    if r.get("tipo"):
        r["tipo"] = _canon(r["tipo"], cfg.tipos) or r["tipo"]
    if r.get("criticidade"):
        r["criticidade"] = _canon(r["criticidade"], cfg.criticidades) or r["criticidade"]
    if r.get("tipo_pessoa"):
        tp = re.sub(r"\s*[,/e]\s*", ",", r["tipo_pessoa"].strip().upper())
        r["tipo_pessoa"] = _canon(tp, cfg.tipos_pessoa) or tp
    if r.get("tabela") and not r.get("tabela_sigla"):
        r["tabela"], r["tabela_sigla"] = tabela_e_sigla(r["tabela"])
    return r


def validar(regra: dict[str, Any], cfg: Config, ctx: Contexto | None = None) -> list[Achado]:
    ctx = ctx or Contexto(set(), set())
    r = canonizar(regra, cfg)
    achados: list[Achado] = []
    tipo = r.get("tipo", "")
    estilo = "erro" if ctx.nova else "aviso"   # exigencias do padrao vigente (ver docstring do modulo)

    # C1 campos obrigatorios ---------------------------------------------------------
    obrig = list(_OBRIGATORIOS_TODAS)
    if normalizar(tipo) == normalizar("Validação"):
        obrig += _OBRIGATORIOS_VALIDACAO
    faltam = [c for c in obrig if not str(r.get(c, "")).strip()]
    if faltam:
        achados.append(Achado("C1_obrigatorios", "erro", f"faltam: {', '.join(faltam)}"))
        return achados  # sem os campos, o resto nao diz nada util

    # C11 listas fechadas ------------------------------------------------------------
    if tipo not in cfg.tipos:
        achados.append(Achado("C11_tipo", "erro", f"tipo '{tipo}' fora de {cfg.tipos}"))
    if r["criticidade"] not in cfg.criticidades:
        achados.append(Achado("C11_criticidade", "erro", f"criticidade '{r['criticidade']}' fora de {cfg.criticidades}: informe exatamente uma opcao, sem '(sugestao)', alternativas ou justificativa"))
    if r["tipo_pessoa"] not in cfg.tipos_pessoa:
        achados.append(Achado("C11_tipo_pessoa", "erro", f"tipo pessoa '{r['tipo_pessoa']}' fora de {cfg.tipos_pessoa}"))
    if not r.get("tabela_sigla"):
        achados.append(Achado("C11_tabela", "erro", "tabela sem sigla: use 'Nome da Tabela (SIGLA)'"))

    # C2 sem sigla em Descricao e Objetivo ------------------------------------------
    # Sigla que existe no catalogo/glossario = nome de campo em texto de negocio: erro.
    # Palavra em maiusculas desconhecida (um acronimo de negocio, por exemplo): so aviso.
    nao = cfg.nao_siglas
    na_logica = set(siglas(r["logica_execucao"], nao))
    for campo in ("descricao", "objetivo"):
        s = [x for x in siglas(r[campo], nao) if x != r.get("tabela_sigla")]
        conhecidas = [x for x in s if x in ctx.siglas_conhecidas]
        desconhecidas = [x for x in s if x not in ctx.siglas_conhecidas]
        # A Governanca aprova Limpezas cuja Descricao lista os mesmos campos da Logica: aviso.
        # Campo tecnico que a Logica nem cita e provavelmente engano: erro.
        soltas = [x for x in conhecidas if x not in na_logica]
        listadas = [x for x in conhecidas if x in na_logica]
        if soltas:
            achados.append(Achado("C2_sigla_em_texto_negocio", "erro", f"{campo} cita campo tecnico que a logica nao usa: {', '.join(soltas)}. Traduza para o termo de negocio."))
        if listadas:
            achados.append(Achado("C2_sigla_em_texto_negocio", "aviso", f"{campo} cita sigla de campo ({', '.join(listadas)}); prefira o termo de negocio."))
        if desconhecidas:
            achados.append(Achado("C2_sigla_em_texto_negocio", "aviso", f"{campo} tem termo em maiusculas: {', '.join(desconhecidas)}. Se for sigla de campo, traduza; se for acronimo de negocio, ignore."))

    # C2b siglas da logica existem ---------------------------------------------------
    s_logica = [x for x in siglas(r["logica_execucao"], nao) if x != r.get("tabela_sigla")]
    if ctx.siglas_conhecidas:
        desconhecidas = [x for x in s_logica if x not in ctx.siglas_conhecidas and "_" in x]
        if desconhecidas:
            achados.append(Achado("C2b_sigla_desconhecida", "aviso", f"nao encontrei no catalogo nem no glossario: {', '.join(desconhecidas)}. Confirme a grafia."))
    elif s_logica:
        achados.append(Achado("C2b_sigla_desconhecida", "aviso", "sem snapshot do catalogo: siglas nao conferidas (rode /atualizar)"))

    # C3 dominios citados no formato (TABELA - CODIGO) -------------------------------
    if re.search(r"dom[ií]nios?\s+permitidos", r["logica_execucao"], re.I) and not re.search(r"\([A-Z][A-Z0-9_/]+\s*-\s*[A-Z0-9]+\)", r["logica_execucao"]):
        achados.append(Achado("C3_dominio_sem_referencia", "aviso", "cita 'dominios permitidos' sem a referencia '(TABELA - CODIGO)'"))

    # C4 forma da Logica e verbo do tipo ---------------------------------------------
    # Padrao vigente: "SE <condicao> ENTAO <acao> SENAO <alternativa>", direto na decisao.
    # Forma anterior, ainda aceita: "A regra <verbo> ..." (Negocio: "O conjunto de regras <verbo> ...").
    verbos = cfg.verbos.get(tipo, [])
    logica_n = normalizar(r["logica_execucao"])
    forma_se = logica_n.startswith("se ") and " entao " in logica_n
    inicio_ok = forma_se or logica_n.startswith("a regra ") or (tipo == "Negócio" and logica_n.startswith("o conjunto de regras "))
    if not inicio_ok:
        achados.append(Achado("C4_inicio_logica", "erro", "Logica de Execucao comeca por 'SE <condicao> ENTAO <acao> SENAO <alternativa>' (forma anterior: 'A regra <verbo>'; Negocio: 'O conjunto de regras <verbo>')"))
    elif verbos:
        verbos_n = [normalizar(v) for v in verbos]
        # A Governanca escreve "A regra verifica se X esta vazio e enriquece com a RBRF": o verbo do
        # tipo pode vir depois de uma condicao. Erro so se ele nao aparecer em lugar nenhum.
        radicais = [v[:-1] for v in verbos_n]  # enriquece -> enriquec (cobre enriquecer/enriquecendo); valida -> valid (cobre 'dado valido')
        if forma_se:
            if not any(rad in logica_n for rad in radicais):
                achados.append(Achado("C4_verbo_do_tipo", "erro", f"a logica nao usa nenhum verbo de {tipo}: {', '.join(verbos)}"))
            if " senao " not in logica_n:
                achados.append(Achado("C4_sem_senao", "aviso", "a forma SE/ENTAO fecha com 'SENAO <alternativa>' (o que acontece quando a condicao nao vale)"))
        else:
            resto = logica_n.replace("o conjunto de regras ", "", 1) if logica_n.startswith("o conjunto") else logica_n[len("a regra "):]
            verbo = primeira_palavra(resto)
            if verbo not in verbos_n and not any(rad in logica_n for rad in radicais):
                achados.append(Achado("C4_verbo_do_tipo", "erro", f"verbo '{verbo}' nao e de {tipo} e a logica nao usa nenhum de: {', '.join(verbos)}"))
    if logica_n.startswith(normalizar(r["descricao"])[:40]) and len(r["descricao"]) >= 40:
        achados.append(Achado("C4_repete_descricao", "aviso", "Logica de Execucao repete a Descricao; comece direto pela decisao"))

    # C5 direcao origem/destino em enriquecimento ------------------------------------
    if tipo == "Enriquecimento":
        alvo = re.search(r"(?:enriquece|preenche|completa|recupera)\s+o\s+campo\s+([A-Z][A-Z0-9_]+|[a-zà-ÿ ]{3,40}?)(?:\s+(?:com|a partir|em|nos|quando|,))", r["logica_execucao"], re.I)
        fonte = re.search(r"(?:com base n[ao]s?|a partir d[aeo]s?|com a (?:base|fonte)|em fonte externa|(?:na|da) base d[ao])\s+([A-Za-zÀ-ÿ_ ]{2,40})", r["logica_execucao"], re.I)
        if not alvo:
            achados.append(Achado("C5_destino", "aviso", "nao identifiquei o campo destino ('A regra enriquece o campo X ...')"))
        if not fonte:
            achados.append(Achado("C5_origem", "aviso", "nao identifiquei a fonte ('com base na RBRF', 'a partir de ...')"))

    # C6 fatos do pedido preservados -------------------------------------------------
    if ctx.pedido:
        texto_final = normalizar(" ".join((r["descricao"], r["logica_execucao"], r["criterio_aplicacao"])))
        pedido_n = normalizar(ctx.pedido)
        perdidos = [f for f in cfg.fatos_dominio if normalizar(f) in pedido_n and normalizar(f) not in texto_final]
        if perdidos:
            achados.append(Achado("C6_fato_perdido", "aviso", f"o pedido cita {', '.join(perdidos)} e o texto final nao"))

    # C7 objetivo especifico ---------------------------------------------------------
    obj_n = normalizar(r["objetivo"])
    verbo_obj = primeira_palavra(r["objetivo"])
    if not re.search(r"(ar|er|ir|or)$", verbo_obj):
        achados.append(Achado("C7_objetivo_infinitivo", "erro", f"Objetivo deve comecar com verbo no infinitivo (comeca com '{verbo_obj}')"))
    for p in cfg.objetivo_proibido:
        if normalizar(p) in obj_n:
            achados.append(Achado("C7_objetivo_generico", "erro", f"formula vazia no Objetivo: '{p}'"))
    palavras_desc = {w for w in normalizar(r["descricao"]).split() if len(w) > 4}
    palavras_obj = {w for w in obj_n.split() if len(w) > 4}
    if palavras_desc and not (palavras_desc & palavras_obj):
        achados.append(Achado("C7_objetivo_desconexo", "aviso", "Objetivo nao compartilha nenhuma palavra de conteudo com a Descricao"))

    # C8 tamanhos --------------------------------------------------------------------
    limites = {"descricao": (20, 1200), "logica_execucao": (20, 1500), "objetivo": (10, 300), "criterio_aplicacao": (10, 600)}
    for campo, (lo, hi) in limites.items():
        n = len(r[campo])
        if n < lo:
            achados.append(Achado("C8_tamanho", "erro", f"{campo} curto demais ({n} caracteres)"))
        elif n > hi:
            achados.append(Achado("C8_tamanho", "aviso", f"{campo} longo demais ({n} caracteres); provavelmente descreve mais de uma regra"))

    # C9 codigo ----------------------------------------------------------------------
    cod = r.get("codigo", "")
    if cod:
        d = decompor_codigo(cod)
        if not d:
            achados.append(Achado("C9_codigo_formato", "erro", f"codigo '{cod}' fora do formato PFX.TT.n"))
        else:
            suf = cfg.sufixo_tipo.get(tipo)
            if suf and d["tipo"] != suf:
                achados.append(Achado("C9_codigo_tipo", "erro", f"codigo {cod} tem sufixo {d['tipo']}, mas {tipo} usa {suf}"))
            pfx_esperado = cfg.prefixos.get(r.get("tabela_sigla", ""))
            if pfx_esperado and d["prefixo"] != pfx_esperado:
                achados.append(Achado("C9_codigo_prefixo", "erro", f"tabela {r['tabela_sigla']} usa prefixo {pfx_esperado}, codigo tem {d['prefixo']}"))
            if cod in ctx.codigos_existentes:
                achados.append(Achado("C9_codigo_repetido", "erro", f"codigo {cod} ja existe"))
    if r.get("rn") and r["rn"] not in ctx.codigos_existentes and r["rn"] not in (ctx.codigos_em_criacao or set()):
        achados.append(Achado("C9_rn_inexistente", "aviso", f"regra de negocio mae {r['rn']} nao encontrada"))

    # C10 nenhuma regra cita outra; a familia (vinculo tecnico) precisa existir -------------
    # Padrao vigente: nenhum campo da ficha cita outra regra, nem pelo codigo nem pelo nome. O que
    # liga RV a RL/RE e a RN e a chave tecnica `familia` da ficha JSON (vira regras_encadeadas no
    # registro interno, para o grafo e o desfazer --cadeia), que nunca aparece no texto.
    proprios = {cod, r.get("codigo_comp", "")}
    for campo in _CAMPOS_TEXTO:
        cit = [c for c in codigos_citados(str(r.get(campo, ""))) if c not in proprios]
        if cit:
            achados.append(Achado("C10_cita_outra_regra", estilo, f"{campo} cita a regra {', '.join(cit)}: descreva a condicao ou o motivo ('segregados como inconsistentes por <motivo>'), nunca o codigo. O vinculo vai na chave 'familia' da ficha."))
    conhecidos = ctx.codigos_existentes | (ctx.codigos_em_criacao or set())
    for c in r.get("regras_encadeadas", []):
        if c in proprios:
            continue
        if conhecidos and c not in conhecidos:
            achados.append(Achado("C10_encadeamento_inexistente", "erro", f"familia/encadeamento cita {c}, que nao existe nem esta sendo criada junto (use --junto COD1,COD2)"))
        dc = decompor_codigo(c)
        if tipo == "Validação" and dc.get("tipo") not in ("RL", "RE", "RN"):
            achados.append(Achado("C10_encadeamento_tipo", "aviso", f"Validação normalmente se liga a Limpeza (RL) ou Enriquecimento (RE); familia cita {c}"))
    if tipo == "Validação" and "segregar" not in normalizar(r["acao_dado_invalido"]):
        achados.append(Achado("C10_segregar", "aviso", "Acao para dado invalido normalmente comeca com 'Segregar como inconsistente: \"<motivo curto>\"'"))

    # C15 marcador esquecido ("<valor concreto>") ----------------------------------------
    for campo in _CAMPOS_TEXTO:
        m = _MARCADOR.search(str(r.get(campo, "")))
        if m:
            achados.append(Achado("C15_marcador", "erro", f"{campo} ainda tem o marcador {m.group(0)}: substitua por dado confirmado (ou pergunte ao usuario)"))

    # C16 acao para dado valido explicita ---------------------------------------------
    if tipo == "Validação" and normalizar(r["acao_dado_valido"]).strip(" .") in _ACAO_VALIDA_VAGA:
        achados.append(Achado("C16_acao_valida_vaga", estilo, "Acao para dado valido vaga ('Manter dado'). Se nada muda: 'Manter o dado validado, sem alteracoes.'"))

    # C17 exemplo concreto (Validacao) ---------------------------------------------------
    if tipo == "Validação":
        ex_n = normalizar(r["exemplo"])
        if len(ex_n) < 40 or not re.search(r"\b(valido|invalido)\b", ex_n):
            achados.append(Achado("C17_exemplo_generico", estilo, "Exemplo deve demonstrar um caso: 'Dado analisado: <valor>. Como <aplicacao do criterio>, o dado e valido/invalido; <acao esperada>.'"))

    # C18 siglas fora dos campos Tabela, Criterio e Logica ----------------------------------
    for campo in _CAMPOS_SEM_SIGLA_ESTILO:
        s = [x for x in siglas(str(r.get(campo, "")), nao) if x != r.get("tabela_sigla") and (x in ctx.siglas_conhecidas or "_" in x)]
        if s:
            achados.append(Achado("C18_sigla_fora_do_lugar", estilo, f"{campo} cita sigla ({', '.join(s)}); siglas de campo e tabela so nos campos Tabela, Criterio de Aplicacao e Logica de Execucao"))

    # C19 observacao x pontos de atencao ------------------------------------------------
    obs_n = normalizar(str(r.get("observacao", "")))
    if re.search(r"\b(ia|copilot|agente|modelo|gerad[oa]|pendente|pendencia|duvida|a confirmar|confirmar com)\b", obs_n):
        achados.append(Achado("C19_observacao_processo", "aviso", "Observacao registra fatos, limites e excecoes da regra; duvidas, pendencias e comentarios sobre a criacao vao em Pontos de atencao"))

    # C20 criterio de aplicacao comeca por 'Executar' ---------------------------------------
    if not normalizar(r["criterio_aplicacao"]).startswith("executar"):
        achados.append(Achado("C20_criterio_forma", "aviso", "Criterio de Aplicacao comeca com 'Executar em todos os registros que...'"))

    # C13 tabela qualificada citada e fora do indice ----------------------------------
    citadas = tabelas_qualificadas(" ".join((r["logica_execucao"], r["criterio_aplicacao"], ctx.pedido or "")))
    if citadas and ctx.tabelas_conhecidas is not None:
        fora = [t for t in citadas if t.lower() not in ctx.tabelas_conhecidas and t.split(".")[-1].lower() not in ctx.tabelas_conhecidas]
        if fora:
            achados.append(Achado("C13_tabela_fora_do_indice", "aviso", f"tabela(s) citada(s) e nao incluida(s) no indice: {', '.join(fora)}. Rode: python -m cdflw incluir-tabela <fqn>"))

    # C14 teste no dado para o que apaga ou e critico -----------------------------------
    if (tipo == "Limpeza" or r["criticidade"] in ("Alta", "Muito Alta")) and not str(r.get("teste_no_dado", "")).strip():
        achados.append(Achado("C14_nao_testado_no_dado", "aviso", "regra de Limpeza ou de criticidade alta sem teste no dado (python -m cdflw testar-regra ficha.json)"))

    # C12 Resultado: efeito concreto, sem rotulos ----------------------------------------
    res_n = normalizar(r["resultado"])
    if _ROTULO_RESULTADO.search(res_n):
        achados.append(Achado("C12_resultado_rotulo", estilo, "Resultado com rotulos 'Sucesso:/Falha:' ou 'Valido:/Invalido:'. Diga o efeito concreto e o estado final: 'Registros com dados que nao atendem ao criterio sao segregados como inconsistentes.'"))
    elif not re.search(r"\b(registros?|dados?|campos?|cadastros?)\b", res_n):
        achados.append(Achado("C12_resultado", "aviso", "Resultado descreve o que aconteceu com os dados ou registros (um unico resultado, sem cenarios alternativos)"))
    return achados


def resumo(achados: list[Achado]) -> str:
    erros = [a for a in achados if a.nivel == "erro"]
    avisos = [a for a in achados if a.nivel == "aviso"]
    linhas = [f"{len(erros)} erro(s), {len(avisos)} aviso(s)"]
    linhas += [str(a) for a in erros] + [str(a) for a in avisos]
    return "\n".join(linhas)


def calibrar(regras: list[dict[str, Any]], cfg: Config, ctx: Contexto) -> dict[str, Any]:
    """Roda o validador sobre as aprovadas. Erros aqui apontam para o validador, nao para a regra."""
    por_check: dict[str, int] = {}
    reprovadas: list[dict[str, Any]] = []
    incompletas: list[dict[str, Any]] = []
    for r in regras:
        ach = validar(r, cfg, ctx)
        erros = [a for a in ach if a.nivel == "erro"]
        for a in ach:
            por_check[a.check] = por_check.get(a.check, 0) + 1
        if not erros:
            continue
        item = {"codigo": r.get("codigo") or r.get("nome"), "erros": [str(a) for a in erros]}
        # campo vazio na propria fonte (ex.: 'Resultado: nan' no export) e lacuna do dado, nao do validador
        if all(a.check == "C1_obrigatorios" for a in erros):
            incompletas.append(item)
        else:
            reprovadas.append(item)
    return {"total": len(regras), "reprovadas": reprovadas, "incompletas_na_fonte": incompletas,
            "por_check": dict(sorted(por_check.items()))}


# ==========================================================================================
# gravar: Grava uma regra aprovada por voce: linha no Excel + ficha em Markdown para colar no CadFlow.
# ==========================================================================================




ROTULOS = {
    "codigo_regra": "Código da regra", "codigo_regra_comp": "Código composto", "nome_regra": "Nome da regra",
    "tipo_regra": "Tipo", "criticidade": "Criticidade", "tabela": "Tabela", "tipo_pessoa_afetada": "Tipo de pessoa",
    "descricao_regra": "Descrição", "objetivo": "Objetivo", "criterio_aplicacao": "Critério de Aplicação",
    "logica_execucao": "Lógica de Execução", "resultado": "Resultado", "exemplo": "Exemplo",
    "acao_dado_valido": "Ação para dado válido", "acao_dado_invalido": "Ação para dado inválido",
    "regras_encadeadas": "Regras encadeadas", "codigos_regra_geral": "Regra geral", "observacao": "Observação",
    "metrica_monitoramento": "Métrica de monitoramento", "status_cdflw": "Status no cdflw", "criado_em": "Criado em",
    "modelo_usado": "Modelo usado", "teste_no_dado": "Teste no dado", "tabela_uc": "Tabela no catálogo", "lote": "Lote (rodada)",
    "pontos_atencao": "Pontos de atenção",
}

# chave interna da regra -> coluna do Excel
_DE_PARA = {
    "codigo": "codigo_regra", "codigo_comp": "codigo_regra_comp", "nome": "nome_regra", "tipo": "tipo_regra",
    "criticidade": "criticidade", "tipo_pessoa": "tipo_pessoa_afetada", "descricao": "descricao_regra",
    "objetivo": "objetivo", "criterio_aplicacao": "criterio_aplicacao", "logica_execucao": "logica_execucao",
    "resultado": "resultado", "exemplo": "exemplo", "acao_dado_valido": "acao_dado_valido",
    "acao_dado_invalido": "acao_dado_invalido", "codigos_regra_geral": "codigos_regra_geral",
    "observacao": "observacao", "pontos_atencao": "pontos_atencao", "metrica_monitoramento": "metrica_monitoramento",
    "modelo_usado": "modelo_usado", "teste_no_dado": "teste_no_dado", "tabela_uc": "tabela_uc", "lote": "lote",
}


def linha_excel(regra: dict[str, Any], cfg: Config) -> dict[str, str]:
    agora = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    valores: dict[str, str] = {c: "" for c in cfg.colunas_excel}
    for chave, col in _DE_PARA.items():
        if col in valores:
            valores[col] = str(regra.get(chave, "") or "")
    tabela = regra.get("tabela", "")
    if regra.get("tabela_sigla") and regra["tabela_sigla"] not in tabela:
        tabela = f"{tabela} ({regra['tabela_sigla']})".strip()
    if "tabela" in valores:
        valores["tabela"] = tabela
    if "regras_encadeadas" in valores:
        # Padrao da Governanca: nenhuma regra cita outra na ficha. O vinculo tecnico (familia) fica so
        # no registro interno, para o grafo e o desfazer --cadeia. A coluna existe porque o formulario tem.
        valores["regras_encadeadas"] = ", ".join(regra.get("regras_encadeadas", [])) if cfg.regras_encadeadas_na_planilha else ""
    if "status_cdflw" in valores:
        valores["status_cdflw"] = regra.get("status_cdflw", "rascunho para colar no CadFlow")
    if "criado_em" in valores:
        valores["criado_em"] = agora
    return valores


def gravar_excel(regra: dict[str, Any], cfg: Config) -> Path:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Font

    caminho = cfg.excel_saida
    caminho.parent.mkdir(parents=True, exist_ok=True)
    colunas = cfg.colunas_excel
    if caminho.exists():
        try:
            wb = load_workbook(caminho)
        except PermissionError:
            raise SystemExit(f"Nao consegui abrir {caminho}. Feche o arquivo no Excel e tente de novo.")
        ws = wb[wb.sheetnames[0]]
        existentes = [str(c.value or "") for c in ws[1]]
        if existentes != colunas and any(existentes):
            colunas = existentes  # respeita o cabecalho que ja esta la
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "regras_novas"
        ws.append(colunas)
        for c in ws[1]:
            c.font = Font(bold=True)
            c.alignment = Alignment(wrap_text=True, vertical="top")
        for i, col in enumerate(colunas, start=1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = 45 if col in ("descricao_regra", "logica_execucao", "criterio_aplicacao", "resultado") else 22
        ws.freeze_panes = "A2"
    valores = linha_excel(regra, cfg)
    ws.append([valores.get(c, "") for c in colunas])
    for c in ws[ws.max_row]:
        c.alignment = Alignment(wrap_text=True, vertical="top")
    try:
        wb.save(caminho)
    except PermissionError:
        raise SystemExit(f"Nao consegui salvar {caminho}. Feche o arquivo no Excel e tente de novo.")
    return caminho


def ficha_markdown(regra: dict[str, Any], cfg: Config) -> str:
    valores = linha_excel(regra, cfg)
    linhas = [f"# {inline(valores.get('codigo_regra') or '(sem codigo)')} — {inline(valores.get('nome_regra', ''))}", ""]
    linhas.append("Copie campo a campo para o formulário do CadFlow. Cada bloco abaixo é um campo.")
    linhas.append("")
    for col in cfg.colunas_excel:
        if col in ("status_cdflw", "criado_em"):
            continue
        v = valores.get(col, "")
        if not v:
            continue
        linhas.append(f"## {ROTULOS.get(col, col)}")
        linhas.append("")
        linhas.append(bloco(v))
        linhas.append("")
    linhas.append("---")
    linhas.append(f"gerado pelo cdflw em {valores.get('criado_em', '')}; modelo: {valores.get('modelo_usado', '') or cfg.modelo}")
    return "\n".join(linhas) + "\n"


def gravar_ficha(regra: dict[str, Any], cfg: Config) -> Path:
    cfg.fichas.mkdir(parents=True, exist_ok=True)
    nome = (regra.get("codigo") or regra.get("nome", "regra")).replace(".", "_").replace(" ", "_")[:60]
    p = cfg.fichas / f"{nome}.md"
    p.write_text(ficha_markdown(regra, cfg), encoding="utf-8", newline="\n")
    return p


def gravar_rascunho_jsonl(regra: dict[str, Any], cfg: Config) -> Path:
    """Registro das regras criadas, para o grafo e o proximo codigo enxergarem."""
    regra.setdefault("lote", lote_atual(cfg))
    p = cfg.dados / "regras_novas.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(regra, ensure_ascii=False) + "\n")
    return p


def lote_atual(cfg: Config, criar: bool = True) -> str:
    """Id da rodada (conversa). `trilha --nova` abre um novo; sem trilha, o primeiro gravar cria."""
    p = cfg.saida / "_lote_atual.txt"
    if p.exists() and p.read_text(encoding="utf-8").strip():
        return p.read_text(encoding="utf-8").strip()
    if not criar:
        return ""
    novo = dt.datetime.now().strftime("%Y%m%d-%H%M%S%f")[:-3]  # milissegundos: duas rodadas no mesmo segundo nao colidem
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(novo + "\n", encoding="utf-8", newline="\n")
    return novo


def novo_lote(cfg: Config) -> str:
    p = cfg.saida / "_lote_atual.txt"
    anterior = p.read_text(encoding="utf-8").strip() if p.exists() else ""
    if p.exists():
        p.unlink()
    novo = lote_atual(cfg)
    if novo == anterior:  # mesmo milissegundo: forca diferenca
        novo = novo + "b"
        p.write_text(novo + "\n", encoding="utf-8", newline="\n")
    return novo


def criadas(cfg: Config) -> list[dict[str, Any]]:
    p = cfg.dados / "regras_novas.jsonl"
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


def expandir_cadeia(codigos: list[str], cfg: Config) -> list[str]:
    """Fecho das regras criadas pelo cdflw ligadas aos codigos: RN -> filhas, RV -> RL/RE, RL -> sua RV, filha -> RN."""

    novas = {normalizar_codigo(r.get("codigo", "")): r for r in criadas(cfg) if r.get("codigo")}
    alvo = {normalizar_codigo(c) for c in codigos if normalizar_codigo(c) in novas}
    mudou = True
    while mudou:
        mudou = False
        for cod, r in novas.items():
            if cod in alvo:
                continue
            rn = normalizar_codigo(r.get("rn", "") or "")
            enc = {normalizar_codigo(c) for c in r.get("regras_encadeadas", [])}
            liga = (rn in alvo) or (enc & alvo) or any(
                cod == normalizar_codigo(novas[a].get("rn", "") or "") or cod in {normalizar_codigo(c) for c in novas[a].get("regras_encadeadas", [])} for a in alvo)
            if liga:
                alvo.add(cod)
                mudou = True
    return sorted(alvo)


def codigos_do_lote(lote: str, cfg: Config) -> list[str]:

    return sorted({normalizar_codigo(r["codigo"]) for r in criadas(cfg) if r.get("codigo") and str(r.get("lote", "")) == lote})


def desfazer(codigo: str, cfg: Config, manter_excel: bool = False) -> dict[str, Any]:
    """Remove uma regra criada pelo cdflw: do registro, da planilha e da ficha. Nao toca regras do export/aprovadas."""

    cod = normalizar_codigo(codigo)
    saida: dict[str, Any] = {"codigo": cod, "registro": 0, "excel": 0, "ficha": False, "avisos": []}
    # registro
    p = cfg.dados / "regras_novas.jsonl"
    if p.exists():
        mantidas, removidas = [], 0
        for l in p.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            try:
                r = json.loads(l)
            except json.JSONDecodeError:
                mantidas.append(l)
                continue
            if normalizar_codigo(r.get("codigo", "")) == cod:
                removidas += 1
            else:
                mantidas.append(l)
        p.write_text("\n".join(mantidas) + ("\n" if mantidas else ""), encoding="utf-8", newline="\n")
        saida["registro"] = removidas
    # excel
    if not manter_excel and cfg.excel_saida.exists():
        from openpyxl import load_workbook

        try:
            wb = load_workbook(cfg.excel_saida)
            ws = wb[wb.sheetnames[0]]
            cab = [str(c.value or "") for c in ws[1]]
            col = cab.index("codigo_regra") + 1 if "codigo_regra" in cab else 1
            linhas = [i for i in range(2, ws.max_row + 1) if normalizar_codigo(str(ws.cell(row=i, column=col).value or "")) == cod]
            for i in reversed(linhas):
                ws.delete_rows(i)
            wb.save(cfg.excel_saida)
            saida["excel"] = len(linhas)
        except PermissionError:
            saida["avisos"].append(f"planilha aberta no Excel: feche e rode de novo para remover a linha ({cfg.excel_saida})")
    # ficha
    nome = cod.replace(".", "_")
    f = cfg.fichas / f"{nome}.md"
    if f.exists():
        f.unlink()
        saida["ficha"] = True
    return saida


# ==========================================================================================
# referencias: Gera as references/ da skill regras-cadflow a partir dos dados da empresa, e deixa o
# ==========================================================================================




MARCA_INICIO = "<!-- cdflw:inicio -->"
MARCA_FIM = "<!-- cdflw:fim -->"

BLOCO_INSTRUCOES = MARCA_INICIO + """
## cdflw (assistente de regras CadFlow)

- O projeto cdflw vive em `cdflw/`. Para criar uma regra de cadastro use o agente `@cdflw` e o prompt `/nova-regra`; para atualizar catalogo e referencias, `/atualizar`.
- Nunca use as skills `databricks-*`, Genie, dbsql ou MCP para consultar o catalogo dentro do fluxo do cdflw: use `python -m cdflw campo <SIGLA>` e `python -m cdflw tabela <nome>`, que leem o snapshot local.
- Dados da empresa ficam em `cdflw/base`, `cdflw/dados` e `cdflw/saida`. Nao os copie para outros lugares.
""" + MARCA_FIM


def _exemplos_por_tipo(regras: list[dict[str, Any]], cfg: Config, por_tipo: int = 2) -> str:
    linhas = ["# Exemplos aprovados pela Governança, por tipo", "",
              "Use como modelo de **tom** e de vocabulário. Os campos abaixo são exatamente os que o CadFlow pede.", "",
              "Atenção: regras aprovadas antes do padrão atual podem citar outra regra pelo código (\"Executar regra X\",",
              "\"segregados pela regra Y\"), usar rótulos \"Válido:/Inválido:\" no Resultado ou \"Manter dado.\" na ação.",
              "O padrão vigente (SKILL.md) não permite nada disso: copie o tom, não essas formas.", ""]
    for tipo in cfg.tipos:
        escolhidas = [r for r in regras if r.get("tipo") == tipo][:por_tipo]
        if not escolhidas:
            continue
        linhas.append(f"## {tipo}")
        linhas.append("")
        for r in escolhidas:
            linhas.append(f"### {r.get('codigo') or ''} {r.get('nome', '')}".strip())
            for campo, rotulo in (("criticidade", "Criticidade"), ("tabela", "Tabela"), ("tipo_pessoa", "Tipo Pessoa"),
                                  ("descricao", "Descrição"), ("objetivo", "Objetivo"), ("criterio_aplicacao", "Critério de Aplicação"),
                                  ("logica_execucao", "Lógica de Execução"), ("resultado", "Resultado"), ("exemplo", "Exemplo"),
                                  ("acao_dado_valido", "Ação dado válido"), ("acao_dado_invalido", "Ação dado inválido")):
                v = str(r.get(campo, "") or "").strip()
                if campo == "tabela" and r.get("tabela_sigla"):
                    v = f"{v} ({r['tabela_sigla']})"
                if v:
                    linhas.append(f"- **{rotulo}:** {inline(v)}")
            linhas.append("")
    return "\n".join(linhas) + "\n"


def _glossario_md(glossario: list[dict[str, str]], limite: int = 300) -> str:
    linhas = ["# Glossário sigla ↔ termo de negócio (extraído das regras aprovadas e do catálogo)", "",
              "| Sigla | Termo de negócio | Tabela | Fonte | Confiança |", "|---|---|---|---|---|"]
    for g in glossario[:limite]:
        linhas.append("| " + " | ".join(celula(x) for x in (g["sigla"], g["termo_negocio"], g.get("tabela_sigla", ""), g.get("fonte", ""), g.get("confianca", ""))) + " |")
    return "\n".join(linhas) + "\n"


def _tabelas_md(snap: dict[str, Any], mapa: dict[str, Any]) -> str:
    linhas = [f"# Tabelas do Unity Catalog ({snap.get('catalogo', '?')}.{snap.get('schema', '?')}, snapshot {snap.get('snapshot_id', 'nenhum')})", ""]
    if mapa:
        linhas += ["## Mapa sigla CadFlow → prefixo de código → tabela UC", "", "| Sigla | Prefixo | Tabela UC | Confirmado |", "|---|---|---|---|"]
        for sig, m in mapa.items():
            conf = "sim" if (m.get("prefixo_confirmado") and m.get("tabela_uc_confirmada")) else "parcial" if (m.get("prefixo_confirmado") or m.get("tabela_uc_confirmada")) else "sugestão"
            linhas.append("| " + " | ".join(celula(x) for x in (sig, m.get("prefixo") or "?", m.get("tabela_uc") or "?", conf)) + " |")
        linhas.append("")
    linhas += ["## Tabelas (nome: comentário, nº de colunas)", ""]
    for nome, t in sorted((snap.get("tabelas") or {}).items()):
        linhas.append(f"- `{inline(nome)}`: {inline(t.get('comentario') or '(sem comentário)')} ({len(t.get('colunas', []))} colunas)")
    linhas += ["", "Para ver as colunas de uma tabela: `python -m cdflw tabela <nome>`. Para uma sigla: `python -m cdflw campo <SIGLA>`."]
    return "\n".join(linhas) + "\n"


def gerar(cfg: Config, kb: dict[str, Any], regras: list[dict[str, Any]], glossario: list[dict[str, str]],
          snap: dict[str, Any], mapa: dict[str, Any]) -> list[Path]:
    pasta = cfg.copilot_fonte / "skills" / "regras-cadflow" / "references"
    pasta.mkdir(parents=True, exist_ok=True)
    escritos = []
    texto_kb = (kb or {}).get("texto", "")
    if texto_kb:
        p = pasta / "padrao.md"
        p.write_text("# Base de conhecimento da Governança (cópia corrigida; a fonte está em base/)\n\n" + quebras(texto_kb).strip() + "\n", encoding="utf-8", newline="\n")
        escritos.append(p)
    p = pasta / "exemplos.md"
    p.write_text(_exemplos_por_tipo(regras, cfg), encoding="utf-8", newline="\n")
    escritos.append(p)
    p = pasta / "glossario.md"
    p.write_text(_glossario_md(glossario), encoding="utf-8", newline="\n")
    escritos.append(p)
    p = pasta / "tabelas.md"
    p.write_text(_tabelas_md(snap, mapa), encoding="utf-8", newline="\n")
    escritos.append(p)
    return escritos


ARQUIVOS_COPILOT = ("agents/cdflw.agent.md", "skills/regras-cadflow/SKILL.md", "skills/nova-regra/SKILL.md",
                    "skills/refazer/SKILL.md", "skills/atualizar/SKILL.md")


def instalar_copilot(cfg: Config) -> list[str]:
    """Confere os arquivos do Copilot no .github da raiz, acrescenta o bloco do cdflw nas instrucoes
    gerais (idempotente) e liga as skills no settings.json. Devolve o que falta."""
    gh = cfg.copilot_fonte
    faltam = [a for a in ARQUIVOS_COPILOT if not (gh / a).exists()]
    ci = gh / "copilot-instructions.md"
    atual = ci.read_text(encoding="utf-8") if ci.exists() else ""
    if MARCA_INICIO in atual:
        novo = re.sub(re.escape(MARCA_INICIO) + r".*?" + re.escape(MARCA_FIM), lambda _m: BLOCO_INSTRUCOES, atual, flags=re.S)
    else:
        novo = (atual.rstrip() + "\n\n" if atual.strip() else "# Instruções do workspace\n\n") + BLOCO_INSTRUCOES + "\n"
    ci.parent.mkdir(parents=True, exist_ok=True)
    ci.write_text(novo, encoding="utf-8", newline="\n")
    _ajustar_settings(cfg)
    return faltam


def trocar_modelo(cfg: Config, modelo: str) -> bool:
    """Grava `model:` no agente do .github da raiz (e o que o Copilot le)."""
    p = cfg.copilot_fonte / "agents" / "cdflw.agent.md"
    if not p.exists():
        return False
    texto = p.read_text(encoding="utf-8")
    novo = re.sub(r"^model:\s*.*$", f"model: '{modelo}'", texto, count=1, flags=re.M)
    p.write_text(novo, encoding="utf-8", newline="\n")
    return True


def _ajustar_settings(cfg: Config) -> None:
    """Liga skills e fixa UTF-8 no settings.json da raiz. Se o arquivo tiver comentarios, nao mexe."""
    p = cfg.raiz_workspace / ".vscode" / "settings.json"
    desejado = {"chat.useAgentSkills": True, "files.encoding": "utf8"}
    try:
        atual = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, json.JSONDecodeError):
        return
    if all(atual.get(k) == v for k, v in desejado.items()):
        return
    atual.update(desejado)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(atual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
