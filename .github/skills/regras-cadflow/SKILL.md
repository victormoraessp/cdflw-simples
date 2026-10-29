---
name: regras-cadflow
description: 'Padrão CadFlow para escrever regras de cadastro de clientes (tipos, criticidade, os 15 campos, forma SE/ENTÃO/SENÃO, o que nunca citar). Use ao criar, revisar ou classificar uma regra de cadastro PF/PJ.'
---

# Regras de cadastro no padrão CadFlow

Uma regra do CadFlow é um registro com os campos abaixo. A Governança aprova pelo texto, então
forma importa tanto quanto conteúdo. Leia [o padrão completo](references/padrao.md) para a
taxonomia, [os exemplos aprovados](references/exemplos.md) para ver o tom da Governança,
[o glossário](references/glossario.md) para traduzir sigla ↔ termo de negócio e
[as tabelas](references/tabelas.md) para o catálogo e o mapa sigla → prefixo → tabela.
(Os arquivos só são carregados quando referenciados assim.)

Os exemplos aprovados são modelo de **tom e vocabulário**, não de forma: regras antigas citam
outras regras pelo código e usam rótulos no Resultado. O padrão vigente, abaixo, não permite isso.
O validador (`python -m cdflw validar`) reprova regra nova que fuja dele.

## Os tipos e o verbo da Lógica

| Tipo | Sufixo do código | Verbo que a Lógica usa | Papel |
|---|---|---|---|
| Negócio | RN | verifica/garante/consolida/agrupa | agrupa as regras de um campo ou tema; é criada primeiro; só aprova quando todas as filhas aprovam |
| Validação | RV | verifica/valida/confere ("considerar o dado válido") | classifica o dado como válido ou inválido e **segrega** o inconsistente |
| Enriquecimento | RE | enriquece/preenche/completa/recupera | preenche ou corrige com fonte interna/externa (PSDC, RBRF, Quod, Bureau…) |
| Limpeza | RL | apaga/remove/limpa/saneia/padroniza | trata o que foi segregado e não dá para recuperar |
| Retroalimentação | RR | retroalimenta/equaliza/atualiza | devolve o resultado da governança aos sistemas de origem |
| Regra Geral | RG | define/designa/classifica | critério transversal (ex.: cliente ativo na Receita) usado por outras regras |

Código: `PFX.TT.n`, onde PFX são as 3 letras da tabela (ver `references/tabelas.md`) e n é o próximo
número livre daquele prefixo e tipo. Quando a regra pertence a uma Regra de Negócio, o código
composto é `PFX.RNk.TTn`.

## Os campos (ordem do formulário)

1. **Nome da regra**: curto, começa com o substantivo da ação: "Validação do código da nacionalidade", "Saneamento do apelido com termos proibidos", "Enriquecimento de nome social".
2. **Tipo**: um dos seis acima.
3. **Criticidade**: informe exatamente uma opção: **Baixa**, **Média** ou **Alta**, definida conforme `references/padrao.md` (impacto da falha, complexidade, fluxo de aprovação). Nunca acrescente "(sugestão)", alternativas ou justificativas junto ao valor. Se tiver dúvida, pergunte ao usuário antes de preencher.
4. **Tabela**: "Nome da Tabela (SIGLA)". Ex.: "Informações de Contato (INFO_CNTTO)". É o único lugar, além dos campos 8 e 9, onde o nome técnico da tabela aparece.
5. **Tipo Pessoa**: PF, PJ ou PF,PJ.
6. **Descrição**: 1 a 3 frases, **linguagem de negócio, sem sigla**. O que a regra faz e por quê. Ex.: "Apaga o valor do campo apelido de pessoa física, pois contém termos proibidos."
7. **Objetivo**: deve explicitar **o motivo da regra** (qual problema, divergência ou necessidade justifica sua criação) e o resultado pretendido; não se limite a nomear a ação ou o assunto. Formule de modo específico, sem siglas de campos ou nomes de tabelas, começando por verbo no infinitivo. Ex.: "Corrigir a razão social divergente da informação encontrada na base da Receita." Para uma validação: "Identificar registros cujo código de nacionalidade não pertence aos valores permitidos." Evite objetivos genéricos como "garantir a qualidade dos dados".
8. **Critério de Aplicação**: informa quando/onde a regra roda e **cita a tabela ou o campo utilizado**. Começa com "Executar em todos os registros que…" ou, quando aplicável, "Executar em todos os registros segregados como inconsistentes por <motivo/condição>". **Nunca cite outra regra pelo código neste campo**; descreva a condição ou o motivo que caracteriza os registros, sem depender do identificador de uma regra que pode mudar. Na ficha da regra, referências a tabelas ou campos utilizados só podem aparecer nos campos 4, 8 e 9; a tabela principal também deve ser identificada no campo 4, conforme o formulário.
9. **Lógica de Execução**: seja sucinto e comece diretamente pela decisão, sem contextualização nem repetição da Descrição ou do Critério de Aplicação. Use **SE <condição> ENTÃO <ação> SENÃO <alternativa>**, de forma explícita e objetiva. Inclua somente os campos, domínios, fontes e mapeamentos necessários para entender e executar a decisão; cite siglas e, quando aplicável, domínios no formato `(TABELA - CODIGO)`. Mantenha referências a tabelas e campos restritas aos campos 4, 8 e 9 da ficha. Ex.: "SE CMPO_NAC pertencer aos domínios permitidos (TDDD - XDOM001) ENTÃO considerar o dado válido. SENÃO considerar o dado inválido." Exemplo de enriquecimento: "SE CMPO_RZ_SOCIAL estiver nulo ou inconsistente ENTÃO preenchê-lo com CMPO_RZ_SOCIAL_EMPR da Receita Federal. SENÃO mantê-lo."
10. **Resultado**: descreve em uma frase **o efeito concreto produzido pela regra e o estado final dos dados ou registros**. Não use rótulos genéricos como "Sucesso", "Falha", "Válido" ou "Inválido", nem se limite a classificar o resultado; diga o que aconteceu com os dados. Inclua um único resultado, sem listar cenários alternativos. Ex.: "Registros com dados que não atendem ao critério são segregados como inconsistentes."

Só para **Validação**:

11. **Exemplo**: obrigatório em toda regra de Validação; nunca omita nem preencha com uma frase genérica que apenas declare "válido" ou "inválido". Demonstre a aplicação da regra em um caso contextualizado: informe o dado de entrada concreto, mostre como ele atende ou não atende à condição/domínio da regra e indique a classificação e a ação esperadas. Formato: "Dado analisado: <valor concreto>. Como <aplicação do critério>, o dado é <válido/inválido>; <ação esperada>." Substitua todos os marcadores por dados confirmados ao gerar a regra. Use dados fornecidos pelo usuário ou confirmados nas referências (`python -m cdflw exemplos` traz valores reais mascarados); não invente valores de domínio, códigos ou fontes. Se faltarem informações para formular um caso real sem suposição, peça esclarecimento antes de concluir a regra. Não inclua neste campo siglas de campos ou nomes de tabelas, que são permitidos somente nos campos 4, 8 e 9.
12. **Ação para dado válido**: descreva explicitamente o que fazer quando o dado atende ao critério da validação. Se nenhuma alteração for necessária, use: "Manter o dado validado, sem alterações." Não use a formulação vaga "Manter dado." nem invente ações posteriores não informadas.
13. **Ação para dado inválido**: descreva a ação e o motivo da inconsistência, por exemplo: `Segregar como inconsistente: "<motivo curto>".` Não cite nem indique outra regra neste campo.

## Campos complementares

14. **Observações**: registre somente fatos, limites, exceções ou particularidades da própria regra que não estejam descritos adequadamente nos demais campos. Não use este campo para comentar o processo de criação da regra, registrar dúvidas ou listar análises pendentes.
15. **Pontos de atenção**: registre dúvidas, informações a confirmar ou análises pendentes para concluir ou aprovar a regra. Formule cada ponto de modo específico. Não use este campo para repetir observações factuais da regra nem para comentar o trabalho da IA. Deixe vazio quando não houver pontos pendentes.

## Regras relacionadas

- Nunca cite outra regra em nenhum campo da ficha, nem pelo código nem pelo nome. Descreva diretamente o motivo da inconsistência, o estado do dado e a ação aplicável, sem apontar para uma regra relacionada.
- Não gere nem preencha o campo `regras_encadeadas` da ficha/planilha; ele fica vazio. O vínculo entre as regras criadas juntas (RN mãe, RV, RL/RE) vai **só** na chave técnica `familia` do JSON (lista de códigos), que nunca aparece no texto: ela serve ao grafo e ao `desfazer --cadeia`.
- Se a solicitação exigir validação e tratamento, mantenha cada ação em sua própria regra, mas não crie referências cruzadas entre elas no texto.
- Enriquecimento com duas fontes vira duas regras independentes; defina a aplicação da segunda pelos registros ainda não preenchidos e elegíveis para essa fonte, sem mencionar a primeira regra.
- Um Enriquecimento diz **destino** ("enriquece o campo X") e **origem** ("com base na RBRF").

## O que nunca fazer

- Inventar sigla, domínio, fonte ou código. Confirme com `python -m cdflw campo` e `proximo-codigo`.
- Pôr sigla em Descrição, Objetivo, Resultado, Exemplo, Ações, Observações ou Pontos de atenção.
- Deixar um marcador `<assim>` no texto final.
- Fundir duas regras em uma. Se o pedido tem "valida e apaga", são duas.
- Afirmar o que o usuário não disse. Dúvida vira pergunta, não suposição (e, se ficar pendente, vai em Pontos de atenção).
