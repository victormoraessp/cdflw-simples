# Manual do cdflw: tudo que o agente faz, como funciona por dentro e como manter

Para quem usa e para quem mantém, em linguagem simples. Se você só quer criar uma regra, leia o
`README.md` e a seção 2. Se algo deu errado, vá à seção 4 (desfazer e refazer) ou à 11 (problemas).

Convenções: `/comando` é algo que você digita no chat do Copilot; `python -m cdflw comando` é um
comando de terminal que o agente roda sozinho (você também pode rodar), sempre a partir da raiz do
repositório. Caminhos como `cdflw\base` são relativos a essa raiz.

---

## 1. A ideia

```mermaid
flowchart LR
    U[Você] -->|texto livre| A[@cdflw no Copilot]
    A -->|comandos| C[python -m cdflw]
    C --> UC[(snapshot do Unity Catalog)]
    C --> RG[(regras aprovadas, glossário, grafo)]
    C -->|validador| A
    A -->|proposta e perguntas| U
    U -->|ok| OUT[Excel + ficha + grafo.html]
    OUT --> CF[CadFlow: você cola]
```

Tudo que não precisa de inteligência artificial é código Python determinístico: ler os arquivos da
Governança, baixar o catálogo, montar o grafo, validar, gravar, desfazer. O modelo só entra para
escrever o texto da regra e conversar com você. Por isso o agente nunca "decora" nada: ele consulta
comandos, e os comandos consultam arquivos locais (a "foto" do catálogo), não o Databricks ao vivo,
exceto nos testes no dado.

O que o agente **não** faz: não escreve no CadFlow (você cola), não altera dado no Databricks (só lê,
com valores mascarados), não grava sem o seu "ok", não inventa campo, tabela, domínio ou código.

## 2. Os comandos de chat

| Você digita | O que acontece | Quando usar |
|---|---|---|
| `/atualizar` | lê `cdflw\base`, tira o retrato do catálogo e da linhagem, monta glossário e grafo, calibra o validador nas aprovadas, regenera as referências da skill | a primeira vez; sempre que a Governança aprovar regras novas ou o catálogo mudar |
| `/nova-regra <pedido>` | o fluxo completo de criação (seção 3) | cada regra nova |
| `/refazer <código>` | desfaz uma regra (ou a família dela) já gravada pelo cdflw e recomeça | errou, mudou de ideia, quer testar outro modelo |
| conversa livre com `@cdflw` | ele responde usando os mesmos comandos ("o que existe sobre o campo X?", "quem é afetado se eu mudar a tabela Y?") | dúvidas antes de criar |

## 3. O que acontece numa criação

1. `status`: existe snapshot e existem regras aprovadas? Sem isso, ele pede `/atualizar`.
2. Classifica o tipo (Validação, Enriquecimento, Limpeza, Negócio, Retroalimentação, Regra Geral).
   "Validar e, se inválido, apagar" são **duas regras**, ligadas por baixo (a família) mas
   independentes no texto.
3. `campo` e `tabela`: confirma que os campos existem no catálogo. Se não encontrar, pergunta.
   Tabela de outro schema citada no pedido: `incluir-tabela` traz para o índice.
4. `relacionadas` e `explorar`: o que já existe sobre os mesmos campos, colisões e redundâncias.
5. Pergunta só o que falta (no máximo 3 por vez), sempre com sugestão.
6. Monta os 15 campos seguindo o padrão (seção 8) e pede o código a `proximo-codigo`.
7. Com cluster ou warehouse ligado: `perfil`, `testar-regra`, `exemplos` (seção 6).
8. `validar`: corrige os erros, explica os avisos.
9. Mostra a regra inteira e pergunta "Posso gravar?". Só grava com o seu "ok".

**O que o `gravar` produz:**

| Arquivo | O que é |
|---|---|
| `cdflw\saida\regras_novas.xlsx` | uma linha por regra, colunas na ordem do formulário do CadFlow |
| `cdflw\saida\fichas\<codigo>.md` | a regra campo a campo, para copiar e colar |
| `cdflw\dados\regras_novas.jsonl` | o registro interno das regras criadas (é o que o `desfazer` e o grafo leem) |
| `cdflw\dados\grafo.html` | o grafo das regras com a nova já dentro |
| `cdflw\saida\_trilha.html` | o caminho que o agente percorreu nesta conversa (se a trilha estiver ligada) |

Cada gravação recebe um **lote**: o identificador da rodada (conversa). Ele aparece na saída do
`gravar`, no `status` e na coluna `lote` do Excel. Serve para desfazer tudo de uma vez.

## 4. Desfazer e refazer, em detalhe

### 4.1 Os conceitos

- **Regra criada pelo cdflw** vs. **regra aprovada/do export**: o cdflw só desfaz o que ele mesmo
  gravou (`cdflw\dados\regras_novas.jsonl`). Regras que vieram da Governança (arquivos em
  `cdflw\base`) nunca são tocadas; essas se editam no CadFlow.
- **Desfazer** remove a regra de três lugares: do registro interno, da linha correspondente no Excel e
  da ficha `.md`. Em seguida regenera o grafo. O **código fica livre** e o `proximo-codigo` volta a
  sugeri-lo.
- **Lote** é a rodada (conversa). Tudo que foi gravado na mesma conversa tem o mesmo lote.
- **Família** (cadeia) é o conjunto de regras ligadas: a Regra de Negócio mãe, as filhas (RV, RL, RE)
  e as regras que o agente declarou na chave técnica `familia` ao gravar. Como o padrão da Governança
  proíbe citar uma regra dentro de outra, esse vínculo existe só no registro interno.
- **Refazer** = desfazer + criar de novo, reaproveitando o pedido original.

### 4.2 O comando

```
python -m cdflw desfazer <codigos> [--cadeia] [--lote <id>] [--listar]
```

| Forma | O que pega |
|---|---|
| `desfazer ICT.RV.3` | só essa regra |
| `desfazer ICT.RV.3 ICT.RL.2` | as duas |
| `desfazer ICT.RL.2 --cadeia` | a RL, a RV ligada a ela, a RN mãe e tudo mais que estiver na família |
| `desfazer --lote 20261028-153012123` | tudo que foi gravado naquela rodada |
| qualquer forma `+ --listar` | **só mostra** o que seria desfeito; não remove nada |

Saída típica com `--listar`:

```
3 regra(s) a desfazer: ICT.RN.9, ICT.RV.9, ICT.RL.9 (--listar: nada foi removido)
```

e, sem `--listar`:

```
desfeitas: 3 registro(s), 3 linha(s) do Excel, 3 ficha(s)
```

Códigos que não foram criados pelo cdflw são recusados com a explicação ("veio do export",
"não foi criada pelo cdflw"). Planilha aberta no Excel: o comando avisa, remove o registro e a ficha,
e pede para fechar o Excel e repetir para tirar a linha.

### 4.3 Os cenários do dia a dia

**Errei uma regra e quero refazer.** No chat: `/refazer ICT.RV.3`. O agente lista a família
(`--cadeia --listar`), pergunta se é isso, desfaz, e recomeça o `/nova-regra` com o seu pedido
original. Se a família tiver mais regras do que você quer refazer, diga quais; ele desfaz só essas.

**Errei a conversa inteira.** `/refazer lote <id>` (o id está na saída do `gravar` e no `status`).

**Quero testar a mesma regra com outro modelo.** `/refazer ICT.RV.3 com modelo <nome como no
seletor>`. Ele grava o modelo no agente (`configurar --local --modelo`), avisa que a troca vale a
partir da próxima mensagem, e recomeça. A coluna `modelo_usado` do Excel e a ficha guardam qual
modelo escreveu cada versão, então dá para comparar.

**Já colei no CadFlow.** Desfazer no cdflw não apaga nada lá. Refaça, e substitua a versão antiga no
CadFlow com a nova ficha.

**Só quero remover, sem refazer.** `python -m cdflw desfazer <codigo>` direto no terminal, ou peça ao
agente "desfaça a ICT.RV.3 e não recrie".

**Quero ver o que foi criado.** `python -m cdflw status` lista as regras criadas, agrupadas por lote,
com o modelo de cada uma.

### 4.4 O que o desfazer não faz

- Não toca regras aprovadas nem o export da Governança.
- Não apaga a trilha da conversa (`cdflw\saida\_trilha.jsonl`). Antes de refazer, o agente exporta a
  trilha anterior (`trilha --exportar`) para você ter o registro da primeira tentativa.
- Não mexe no CadFlow.
- Não "desdesfaz": uma regra removida só volta sendo criada de novo (a ficha exportada na trilha ajuda).

## 5. O que o `/atualizar` produz (pasta `cdflw\dados`)

| Arquivo | O que é |
|---|---|
| `regras.jsonl` | todas as regras aprovadas e do export, num formato só |
| `glossario.csv` | sigla ↔ termo de negócio, extraído das aprovadas e do catálogo |
| `uc\<schema>.json`, `uc\linhagem.json`, `uc\extras.json` | o retrato do catálogo, a linhagem de colunas e as tabelas incluídas sob demanda |
| `mapa_tabelas.md` | sugestão de sigla → prefixo → tabela (você confirma com `configurar --aceitar-mapa`) |
| `calibracao.json` | o validador rodado nas aprovadas: tem que dar 0 reprovadas |
| `grafo.json`, `grafo.html`, `metricas.json`, `visoes\*.md` | o grafo das regras e as visões de governança |
| `detectados.md` | problemas estruturais (família apontando para regra inexistente, código repetido…) |

Em `.github\skills\regras-cadflow\references\` (fora do git): `padrao.md`, `exemplos.md`,
`glossario.md`, `tabelas.md`, que a skill carrega quando precisa. Os arquivos da Governança em
`cdflw\base` são lidos como estão: o `.md` da base de conhecimento (com os JSON por seção), o `.md`
das aprovadas ("Regra: …" seguido dos campos) e o export `.xlsx` do CadFlow (uma linha por regra).

**Calibração:** as regras aprovadas pela Governança passam pelo validador. Se alguma reprovar, **o
validador está errado**, não a regra. Os checks de estilo do padrão vigente são só avisos para as
aprovadas (seção 8). "Incompletas na fonte" são aprovadas com campo vazio no arquivo de origem.

## 6. Olhar o dado de verdade (cluster ou warehouse)

| Comando | Responde |
|---|---|
| `cluster [--ligar] [--esperar --max 240]` | estado do cluster; liga sem bloquear; espera com progresso (código de saída 2 = ainda subindo) |
| `perfil <tabela> <SIGLA>` | total, nulos, distintos, tamanhos, padrão dominante, valores frequentes (mascarados) |
| `testar-regra ficha.json` | quantos registros a regra marcaria e a taxa; grava `teste_no_dado` |
| `exemplos <tabela> <SIGLA> --onde "<predicado>"` | amostra que atende e que não atende, mascarada, para o campo Exemplo |
| `dominio <TABELA_DOMINIO>` | confirma que a tabela de domínio existe e lista os valores |
| `sobreposicao ficha.json --com <regra>` | quantos registros a regra nova marca que outra já marca |
| `incluir-tabela catalogo.schema.tabela --siglas A,B` | traz uma tabela de outro schema para o índice, procurando homônimas e ranqueando a mais oficial |

Proteções: só `SELECT`, um comando por vez, amostragem acima de `max_linhas_sem_amostra`,
valores mascarados (dígito vira 9, letra vira X), nenhum valor de amostra vai para a ficha ou o
Excel. Teste no dado é obrigatório para Limpeza e para criticidade Alta; se a regra marcar mais da
metade dos registros, o agente para e pergunta.

**Cluster all-purpose desligado.** Metadados (`tabela`, `campo`, `incluir-tabela`) nunca ligam o
cluster: são REST. Os comandos de dado conferem o estado antes: com `auto_ligar_cluster = true`
pedem para ligar e esperam até `espera_cluster_s` (240 s) imprimindo o estado a cada
`intervalo_poll_s`; se ainda não subiu, saem com **código 2** e `CLUSTER PENDENTE`, que para o agente
significa "espere e repita". Um SQL warehouse configurado (`configurar --local --warehouse-nome`)
sobe em segundos e é sempre preferido para SQL.

## 7. Grafo e visões de governança

`cdflw\dados\grafo.html` abre no navegador, sem internet: busca por código, filtros por tipo,
vizinhança, impacto, cores por comunidade. No terminal:

| Comando | Responde |
|---|---|
| `explorar <campo, tabela ou regra>` | tudo sobre o alvo: regras atreladas, cadeia, impacto, redundância |
| `impacto <alvo> [--profundidade N]` | quem é afetado se o campo/regra mudar |
| `redundancias [--limiar 0.6]` | pares de regras parecidas demais (mesmos campos) |
| `cadeias [--so-quebradas]` | as famílias RN → RV → RL/RE e as que estão incompletas |
| `cobertura [--tabela X]` | campos do catálogo sem regra nenhuma |
| `dimensoes` | regras por dimensão de qualidade (completude, validade…) |
| `exportar-grafo` | `cdflw\dados\grafo.gexf` para Gephi |

Nós: regras, campos, tabelas. Arestas: `agrupa` (RN → filhas, pelo código composto), `executa`
(Validação → Limpeza/Enriquecimento, pela `familia` nas regras novas e pelas citações nas antigas),
`le`, `escreve`, `pertence`. A seção "Como ler o grafo" do agente explica como interpretar cada
resposta e o que não concluir.

## 8. O padrão de escrita (o que o validador cobra)

Os 15 campos: nome, tipo, criticidade, tabela, tipo de pessoa, descrição, objetivo, critério de
aplicação, lógica de execução, resultado, exemplo, ação para dado válido, ação para dado inválido,
observações e pontos de atenção. O texto completo está em
`.github\skills\regras-cadflow\SKILL.md`. O essencial:

- **Nenhuma regra cita outra**, em campo nenhum, nem por código nem por nome. O vínculo entre regras
  criadas juntas é técnico (chave `familia`) e não aparece no texto.
- **Siglas** de campo e tabela só em Tabela, Critério de Aplicação e Lógica de Execução.
- **Lógica** direta na decisão: `SE <condição> ENTÃO <ação> SENÃO <alternativa>`.
- **Resultado** diz o efeito concreto nos dados, sem "Válido:/Inválido:" ou "Sucesso:/Falha:".
- **Exemplo** (Validação) é um caso real: "Dado analisado: … Como …, o dado é válido/inválido; …".
- **Ação para dado válido** explícita ("Manter o dado validado, sem alterações."); **inválido**:
  `Segregar como inconsistente: "<motivo curto>".`
- **Observações** = fatos da regra; **Pontos de atenção** = dúvidas e pendências para quem aprova.
- Criticidade é exatamente uma opção, sem "(sugestão)".

| Check | Pergunta | Nível |
|---|---|---|
| C1 | campos obrigatórios preenchidos? (Validação exige Exemplo e as duas Ações) | erro |
| C11 | tipo, criticidade e tipo de pessoa estão nas listas, exatamente? tabela tem sigla? | erro |
| C2 | Descrição/Objetivo citam campo técnico que a Lógica nem usa? | erro; se a Lógica também cita, aviso |
| C2b | as siglas da Lógica existem no catálogo ou no glossário? | aviso |
| C3 | "domínios permitidos" vem com `(TABELA - CODIGO)`? | aviso |
| C4 | Lógica começa por SE…ENTÃO (ou "A regra <verbo>") e usa um verbo do tipo? fecha com SENÃO? repete a Descrição? | erro / aviso |
| C5 | Enriquecimento diz destino e origem? | aviso |
| C6 | os fatos do pedido (RBRF, PF, celular…) sobreviveram no texto? | aviso |
| C7 | Objetivo começa em infinitivo, é específico, não é fórmula vazia? | erro / aviso |
| C8 | tamanhos razoáveis? | erro se curto, aviso se longo |
| C9 | código no formato, prefixo da tabela, sufixo do tipo, não repetido? | erro |
| C10 | algum campo cita outra regra? a família aponta para regra existente ou criada junto? | estilo* / erro |
| C12 | Resultado sem rótulos e descrevendo o efeito nos dados? | estilo* / aviso |
| C13 | tabela qualificada citada e fora do índice? | aviso |
| C14 | Limpeza ou criticidade alta sem teste no dado? | aviso |
| C15 | sobrou marcador `<assim>`? | erro |
| C16 | Ação para dado válido vaga ("Manter dado")? | estilo* |
| C17 | Exemplo genérico ou curto demais (Validação)? | estilo* |
| C18 | sigla fora de Tabela/Critério/Lógica? | estilo* |
| C19 | Observação com dúvida/pendência (lugar é Pontos de atenção)? | aviso |
| C20 | Critério começa com "Executar…"? | aviso |

\* **estilo**: erro para regra nova (é o que `validar` e `gravar` fazem) e aviso na calibração das
aprovadas. Assim o padrão vigente é exigido do que se cria agora sem reprovar o que a Governança
aprovou antes dele.

## 9. Trilha da conversa

Com `[trilha].ativa = true` no `config.toml`, cada conversa deixa um registro em
`cdflw\saida\_trilha.jsonl` e um painel ao vivo em `cdflw\saida\_trilha.html` (recarrega sozinho).
Entram todos os comandos que o agente rodou, com a saída completa, e as anotações dele (o que leu,
concluiu, perguntou). A cada `validar` ou `gravar` a trilha guarda a versão da ficha e o diff contra
a anterior. `trilha --nova` abre uma rodada (e um lote novo), `--exportar` gera um Markdown para
arquivar, `--limpar` apaga, `--desligar` desliga tudo. É o caminho observável do agente, não o
"raciocínio" do modelo; custa perto de 1% da conversa.

## 10. Como customizar (`cdflw\config.toml`)

| Seção | O que controla |
|---|---|
| `[databricks]` | catálogo, schema, linhagem; `schemas_preferidos` e `schemas_busca` (tabelas sob demanda); `usar_query_history`, `dias_uso`; `auto_ligar_cluster`, `espera_cluster_s`, `intervalo_poll_s`; `max_linhas_sem_amostra`, `max_valores_frequentes`, `mascarar_amostras`. Profile, cluster e warehouse são seus e vão em `config.local.toml` (ou vêm da extensão Databricks) |
| `[caminhos]` | onde ficam base/dados/saida, o Excel e as fichas (aceita caminho absoluto, ex.: pasta compartilhada para `base`); `raiz_workspace` (`..`: a raiz do repositório) |
| `[copilot]` | `modelo` do agente (a troca é feita no `.github\agents\cdflw.agent.md` por `configurar --modelo`) |
| `[trilha]` | `ativa` |
| `[analise]` | `limiar_redundancia`; `dimensoes` próprias da casa |
| `[regras]` | tipos, criticidades, tipos de pessoa; sufixo de código por tipo; **verbos aceitos por tipo**; fatos de domínio; fórmulas proibidas no Objetivo; palavras em maiúsculas que não são siglas |
| `[mapa_tabelas.prefixo]` / `[mapa_tabelas.uc]` | sigla CadFlow → prefixo e → tabela do catálogo (o que você confirmou) |
| `[excel]` | ordem e nomes das colunas do `regras_novas.xlsx`; `regras_encadeadas_na_planilha` (`false`: a coluna sai vazia, como o padrão manda) |

Edite e salve; os comandos leem o arquivo a cada execução. `config.local.toml` sobrepõe o da equipe e
não vai para o git.

**O padrão de escrita** mora em `.github\skills\regras-cadflow\SKILL.md`. Se mudar uma regra de
forma, mude também o validador (`cdflw\nucleo.py`, função `validar`) e rode
`python -m pytest cdflw/tests -q` e `/atualizar` para ver a calibração: os dois precisam contar a mesma
história. **Colunas do Excel**: `[excel].colunas` e, em `nucleo.py`, `_DE_PARA`, `ROTULOS` e
`CAMPOS_REGRA` (foi assim que `pontos_atencao` entrou).

## 11. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| o agente não aparece no seletor | `.github` incompleto ou skills desligadas | `python -m cdflw instalar` (lista o que falta e liga `chat.useAgentSkills`); recarregue a janela |
| Copilot diz que o terminal devolveu saída vazia | captura do terminal falhou nessa máquina | o agente lê `cdflw\saida\_ultimo_comando.txt`; para `pip`/`pytest`, peça para redirecionar com `*> arquivo` e ler o arquivo |
| `Cluster ... does not exist` | id errado | `python -m cdflw recursos` e `configurar --local --cluster-nome "<nome>"` |
| comando de dado "trava" ou o agente desiste com o cluster desligado | cluster all-purpose subindo (minutos) | `cluster --ligar`, depois `cluster --esperar`; código 2 = repetir; ou configure um SQL warehouse |
| `Nao consegui salvar ... Feche o arquivo no Excel` | planilha aberta | fechar o Excel e repetir |
| `C2b_sigla_desconhecida` | sigla não existe no snapshot nem no glossário | conferir grafia com `campo`; se o catálogo mudou, `/atualizar` |
| `C9_codigo_repetido` numa regra que quero refazer | a versão anterior ainda está gravada | nunca invente outro código: `/refazer <codigo>` |
| `sem snapshot do catalogo` | nunca rodou `/atualizar` ou falhou | `/atualizar`; ver profile e proxy |
| `has no DEFAULT profile configured` ou `profile ... nao existe em ~/.databrickscfg` | a extensão Databricks em modo bundle não grava `project.json`; o cdflw tenta o host de `.databricks\.databricks.env` e do `databricks.yml` em `~\.databrickscfg`, e não achou | `python -m cdflw status` mostra os profiles disponíveis; fixe o seu com `configurar --local --profile <nome>` |
| a regra marcou 99% dos registros no teste | condição invertida ou pedido errado | o agente para e pergunta; responda antes de gravar |
| Skills `databricks-*` sendo acionadas | pacote AI tools instalado | o agente é instruído a não usá-las |

## 12. Segurança e custo

- Nada da empresa sai da máquina: `cdflw\base`, `dados`, `saida` e `config.local.toml` ficam locais e
  fora do git.
- O Databricks é acessado com um profile do `~/.databrickscfg` (o da extensão, ou o de mesmo host quando a
  extensão está em modo bundle); o cdflw não guarda credencial.
- Custo de Copilot: uma conversa por regra, com o modelo fixo do agente. Os comandos não gastam
  crédito. O `/atualizar` quase não gasta (só a mensagem que resume a saída).

## 13. Manutenção

- **A Governança aprovou regras novas / o catálogo mudou**: arquivos novos em `cdflw\base`,
  `/atualizar`; se aparecer sigla de tabela nova, `configurar --aceitar-mapa`.
- **Mudei o validador ou a skill**: `python -m pytest cdflw/tests -q`, depois `/atualizar` e olhe a
  calibração (0 reprovadas).
- **Versão nova do cdflw**: copie os arquivos por cima (`status` mostra a versão), `instalar`,
  `/atualizar` se skill, base ou validador mudaram. Compare o `config.toml` antes de sobrescrever.
- **Outro agente nos mesmos moldes**: `docs\TUTORIAL_AGENTE.md`.

## 14. Glossário

- **CadFlow**: o aplicativo onde as regras vivem oficialmente. O cdflw prepara; você cola lá.
- **Regra de Negócio (RN)**: a "mãe" que agrupa Validação (RV), Enriquecimento (RE), Limpeza (RL) de um campo ou tema.
- **Código**: `PFX.TT.n` (prefixo da tabela, tipo, número). Composto: `PFX.RNk.TTn`.
- **Sigla**: nome técnico de campo ou tabela. Permitida só em Tabela, Critério e Lógica.
- **Snapshot**: a foto do catálogo em `cdflw\dados\uc\`.
- **Linhagem**: de qual coluna de origem cada coluna deriva (`system.access.column_lineage`).
- **Glossário**: sigla ↔ termo de negócio, extraído das aprovadas e do catálogo.
- **Calibração**: rodar o validador nas aprovadas para provar que ele reconhece o padrão da Governança.
- **Lote**: a rodada em que regras foram gravadas; `desfazer --lote <id>` desfaz todas.
- **Família**: RN mãe, filhas e regras ligadas pela chave técnica `familia`; `desfazer --cadeia` desfaz todas.
- **Pontos de atenção**: campo da ficha para dúvidas e pendências de quem aprova.
