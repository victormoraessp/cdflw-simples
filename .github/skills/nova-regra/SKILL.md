---
name: nova-regra
description: 'Cria uma regra de cadastro no padrão CadFlow a partir de um texto livre. Invoque com /nova-regra seguido do pedido.'
argument-hint: 'descreva a regra em texto livre (campo, tabela, o que validar/enriquecer/apagar)'
disable-model-invocation: true
user-invocable: true
---

# /nova-regra

Este fluxo foi desenhado para o agente **@cdflw** (modelo fixo, ferramentas no terminal). Se você não
estiver rodando como `@cdflw`, diga ao usuário para selecionar esse agente no seletor e continue
mesmo assim seguindo exatamente os passos abaixo e a skill [regras-cadflow](../regras-cadflow/SKILL.md).

0. Se a trilha estiver ligada, rode `python -m cdflw trilha --nova "<pedido resumido>"` e avise o usuário
   que ele pode acompanhar em `cdflw/saida/_trilha.html`. Registre com `python -m cdflw anotar`
   o que ler (`--leu skill:nova-regra`, `--leu skill:regras-cadflow`), cada conclusão, cada pergunta
   (`--pergunta`) e cada resposta (`--resposta`).
1. Rode `python -m cdflw status`. Sem snapshot do catálogo ou sem regras aprovadas: pare e peça `/atualizar`.
2. Classifique o tipo pelo pedido. "Validar e, se inválido, apagar/enriquecer" são **duas** regras,
   independentes no texto (nenhuma cita a outra); crie as duas na mesma conversa e ligue-as pela chave
   técnica `familia` da ficha (lista de códigos), que não aparece no texto.
3. Confirme tabela e campos com `python -m cdflw campo <SIGLA>` e `python -m cdflw tabela <nome>`. Campo
   não confirmado: pergunte, mostrando as candidatas. Pedido com `catalogo.schema.tabela` fora do snapshot:
   `python -m cdflw incluir-tabela <fqn> --siglas A,B` e, se vier "AMBIGUA", pergunte qual usar.
4. `python -m cdflw relacionadas --campos A,B --tabela SIGLA --tipo <tipo>` e
   `python -m cdflw explorar <campo principal>`. Mostre em até 5 linhas o que já existe, colisões e
   redundâncias (a seção "Como ler o grafo" do agente explica o que cada linha significa).
5. Pergunte só o que falta, no máximo 3 perguntas por vez, cada uma com a sua sugestão. O que ficar
   pendente sem bloquear a regra vai em `pontos_atencao`.
6. Monte os 15 campos do CadFlow conforme a skill regras-cadflow (Lógica na forma SE/ENTÃO/SENÃO, Resultado
   concreto, Exemplo com dado real, nenhuma citação a outra regra). Código:
   `python -m cdflw proximo-codigo --tabela <SIGLA da tabela> --tipo <tipo> [--rn PFX.RN.n]`
   (passe a **sigla da tabela**, ex.: `INFO_CNTTO`; o prefixo de 3 letras vem do mapa).
   Grave a ficha JSON em `cdflw/saida/_ficha.json` e valide:
   `python -m cdflw validar cdflw/saida/_ficha.json --pedido "<texto do usuário>" [--junto COD1,COD2]`
   (`--junto` lista os códigos das regras criadas nesta conversa, os mesmos de `familia`).
7. Teste no dado quando houver cluster ou warehouse: antes, `python -m cdflw cluster`; se `TERMINATED`,
   `cluster --ligar`, avise que leva minutos e pergunte se o usuário espera; `cluster --esperar --max 240`.
   Escreva o predicado SQL da Lógica em `sql_teste` e a tabela qualificada em `tabela_uc` na ficha e rode
   `python -m cdflw testar-regra cdflw/saida/_ficha.json`. Código de saída 2 = cluster
   pendente: espere e repita, não invente o número. **Se a regra marcar mais da metade dos registros,
   pare e pergunte ao usuário** se o pedido está certo antes de seguir. Obrigatório para Limpeza e para
   criticidade Alta. Use `python -m cdflw exemplos <tabela> <SIGLA> --onde "<predicado>"` para o campo
   Exemplo (dado concreto, mascarado).
8. Mostre a regra completa em tabela campo/valor, os avisos do validador, os pontos de atenção e, se
   testou, a contagem. Pergunte: "Posso gravar?".
9. Só com "ok" explícito: `python -m cdflw gravar cdflw/saida/_ficha.json`. Informe Excel,
   ficha, `cdflw/dados/grafo.html` e o **lote** da rodada, e lembre que o próximo passo é colar no CadFlow.

Errou ou quer refazer uma regra já gravada pelo cdflw: siga a skill [refazer](../refazer/SKILL.md)
(`/refazer <codigo>`): ela desfaz a versão anterior (o código fica livre de novo) e recomeça. Regras do
export/aprovadas não são desfeitas por aqui.

Se o terminal devolver saída vazia, leia `cdflw/saida/_ultimo_comando.txt`.
