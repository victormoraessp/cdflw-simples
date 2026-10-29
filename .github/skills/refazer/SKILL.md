---
name: refazer
description: 'Refaz uma regra já gravada pelo cdflw: desfaz a versão anterior (registro, planilha, ficha), libera o código e recomeça o fluxo de criação, opcionalmente com outro modelo. Invoque com /refazer <código>.'
argument-hint: 'código(s) da regra, ou "lote <id>", e se quiser "com modelo <nome>"'
disable-model-invocation: true
user-invocable: true
---

# /refazer

Fluxo para o agente **@cdflw**; se você não for ele, peça ao usuário para selecioná-lo e continue.

1. **Identifique a regra.** Se o usuário não deu o código, rode `python -m cdflw status` (lista as
   regras criadas pelo cdflw, por lote, com o modelo de cada uma) e pergunte qual. Se o código não estiver
   nessa lista, é regra do export ou das aprovadas: diga que ela se edita no CadFlow e pare.
2. **Guarde a rodada anterior**, se a trilha estiver ligada: `python -m cdflw trilha --exportar`
   (gera `saida/trilha_<data>.md`; a ficha antiga some no passo seguinte, e esse arquivo é o registro).
3. **Descubra a família.** Um pedido costuma gerar várias regras (RN mãe, RV, RL/RE ligadas pela chave
   `familia`). Rode `python -m cdflw desfazer <codigo> --cadeia --listar`: ele lista a RN, as filhas e as
   ligadas criadas pelo cdflw, sem remover nada. Alternativas: `--lote <id>` pega tudo que foi gravado na
   mesma rodada (o id aparece no `status` e na saída do `gravar`), e vários códigos separados por espaço
   pegam só os indicados. **Mostre a lista ao usuário e pergunte se é isso.**
4. **Desfaça** com o mesmo comando sem `--listar`. Mostre a linha de resultado (registros, linhas do
   Excel, fichas). Se avisar que a planilha está aberta, peça para fechar o Excel e rode de novo.
   Não prossiga sem o desfazer ter saído com sucesso.
5. **Outro modelo?** Se o usuário pediu "com modelo X", rode
   `python -m cdflw configurar --local --modelo "<nome exatamente como no seletor do Copilot>"` e
   `python -m cdflw instalar`, e avise que a troca vale a partir da próxima mensagem (o agente é
   recarregado); peça para ele reenviar `/refazer` ou seguir já com `/nova-regra`.
6. **Recomece:** `python -m cdflw trilha --nova "refazendo <codigo>"` e siga, passo a passo, a skill
   [nova-regra](../nova-regra/SKILL.md), reaproveitando o pedido original (pergunte se mudou algo).
   Os códigos liberados serão sugeridos de novo pelo `proximo-codigo`; recrie a família inteira
   (RN primeiro, depois RV, depois RL/RE) com a chave `familia` preenchida para o grafo fechar.
7. Ao gravar, lembre o usuário de substituir a versão antiga no CadFlow, se ela já tiver sido colada.

Nunca grave uma segunda cópia com o mesmo código sem desfazer, nem invente um código novo para
contornar o aviso `C9_codigo_repetido`. Se o terminal devolver saída vazia, leia
`cdflw/saida/_ultimo_comando.txt`.
