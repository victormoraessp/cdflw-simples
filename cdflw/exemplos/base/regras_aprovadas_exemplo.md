# Regras de Cadastro PF — Base Aprovada (EXEMPLO SINTÉTICO, 8 regras)

## Regra: Consistência do telefone de contato de uma pessoa física

- **Código:** ICT.RN.1
- **Tipo:** Negócio
- **Criticidade:** Alta
- **Tabela:** Informações de Contato (INFO_CNTTO)
- **Tipo Pessoa:** PF
- **Descrição:** Verifica o telefone de contato de pessoa física, buscando qualificar os dados.
- **Objetivo:** Consistir o telefone de contato de pessoa física.
- **Critério de Aplicação:** Executar em todo o cadastro de pessoa física.
- **Lógica de Execução:** O conjunto de regras verifica o conteúdo dos campos de DDD, número e tipo do telefone de contato buscando consistir a informação em todo o cadastro do cliente.
Realiza a validação, enriquecimento e o saneamento dos dados inconsistentes.
- **Resultado:** Registros verificados e mantidos com dados consistentes.
- **Ação dado válido:** Manter a informação consistente.
- **Ação dado inválido:** Para registros inconsistentes, executar as regras previstas, conforme o campo.

---

## Regra: Validação do DDD do telefone de contato

- **Código:** ICT.RV.1
- **Tipo:** Validação
- **Criticidade:** Baixa
- **Tabela:** Informações de Contato (INFO_CNTTO)
- **Tipo Pessoa:** PF
- **Descrição:** Valida se o DDD do telefone de contato está dentro dos domínios permitidos.
- **Objetivo:** Validar o DDD do telefone de contato de pessoa física.
- **Critério de Aplicação:** Executar em todos os registros que possuam conteúdo no campo DDD do telefone de contato.
- **Lógica de Execução:** A regra verifica se o valor contido no campo CMPO_DDD_TEL pertence aos domínios permitidos (TDDD - XDOM001), sendo considerado válido ao atender esta condição.
Se constar valores não pertencentes aos domínios permitidos, o registro será considerado inválido.
- **Resultado:** Válido: registro pertence aos domínios permitidos.
Inválido: registro não pertence aos domínios permitidos.
- **Exemplo:** DDD 11 é válido; DDD 00 é inválido.
- **Ação dado válido:** Manter dado
- **Ação dado inválido:** Segregar como inconsistente: "DDD do telefone invalido".
Executar regra ICT.RL.1.

---

## Regra: Saneamento do DDD do telefone de contato

- **Código:** ICT.RL.1
- **Tipo:** Limpeza
- **Criticidade:** Alta
- **Tabela:** Informações de Contato (INFO_CNTTO)
- **Tipo Pessoa:** PF
- **Descrição:** Apaga o conteúdo do campo DDD do telefone de contato por não pertencer aos domínios permitidos.
- **Objetivo:** Apagar o conteúdo do campo DDD do telefone de contato.
- **Critério de Aplicação:** Executar em todos os registros que foram segregados como inconsistentes pela regra ICT.RV.1.
- **Lógica de Execução:** A regra apaga o conteúdo do campo CMPO_DDD_TEL nos registros que foram segregados como inconsistentes por não pertencer aos domínios permitidos.
- **Resultado:** Sucesso: os campos inconsistentes são apagados.
Falha: registro não apagado.

---

## Regra: Validação do tipo do telefone de contato

- **Código:** ICT.RV.2
- **Tipo:** Validação
- **Criticidade:** Média
- **Tabela:** Informações de Contato (INFO_CNTTO)
- **Tipo Pessoa:** PF
- **Descrição:** Valida se o tipo do telefone de contato é coerente com o número da linha informado.
- **Objetivo:** Validar o tipo do telefone de contato de pessoa física.
- **Critério de Aplicação:** Executar em todos os registros que possuam conteúdo nos campos de tipo e número do telefone de contato.
- **Lógica de Execução:** A regra verifica se o valor contido no campo CMPO_TIPO_TEL é coerente com a faixa do campo CMPO_NUM_TEL, conforme os domínios permitidos (TTIPO_TEL - XDOM002), sendo considerado válido ao atender esta condição.
- **Resultado:** Válido: tipo coerente com o número.
Inválido: tipo incoerente com o número.
- **Exemplo:** Número iniciado em 9 com tipo celular é válido; iniciado em 3 com tipo celular é inválido.
- **Ação dado válido:** Manter dado
- **Ação dado inválido:** Segregar como inconsistente: "Tipo do telefone incoerente com o numero". Executar regra ICT.RE.1.

---

## Regra: Enriquecimento do tipo do telefone de contato

- **Código:** ICT.RE.1
- **Tipo:** Enriquecimento
- **Criticidade:** Média
- **Tabela:** Informações de Contato (INFO_CNTTO)
- **Tipo Pessoa:** PF
- **Descrição:** Enriquece o campo tipo do telefone de contato a partir do número da linha, quando o tipo informado for incoerente.
- **Objetivo:** Enriquecer o tipo do telefone de contato a partir do número da linha.
- **Critério de Aplicação:** Executar em todos os registros que foram segregados como inconsistentes pela regra ICT.RV.2.
- **Lógica de Execução:** A regra enriquece o campo CMPO_TIPO_TEL com base na faixa do campo CMPO_NUM_TEL nos registros segregados como inconsistentes, conforme os domínios permitidos (TTIPO_TEL - XDOM002).
- **Resultado:** Sucesso: o campo tipo do telefone é enriquecido.
Falha: correspondência não confirmada e dado não enriquecido.

---

## Regra: Validação do código do sexo

- **Código:** IBS.RV.1
- **Tipo:** Validação
- **Criticidade:** Baixa
- **Tabela:** Informações Básicas (INFO_BSICO)
- **Tipo Pessoa:** PF
- **Descrição:** Valida se o código do sexo está dentro dos domínios permitidos.
- **Objetivo:** Validar o código do sexo de pessoa física.
- **Critério de Aplicação:** Executar em todos os registros que possuam conteúdo no campo código do sexo.
- **Lógica de Execução:** A regra verifica se o valor contido no campo CMPO_SEXO pertence aos domínios permitidos (TSEXO - XDOM003), sendo considerado válido ao atender esta condição.
- **Resultado:** Válido: registro pertence aos domínios permitidos.
Inválido: registro não pertence aos domínios permitidos.
- **Exemplo:** Valor F é válido; valor X é inválido.
- **Ação dado válido:** Manter dado
- **Ação dado inválido:** Segregar como inconsistente: "Codigo do sexo invalido". Executar regra IBS.RL.1.

---

## Regra: Saneamento do código do sexo

- **Código:** IBS.RL.1
- **Tipo:** Limpeza
- **Criticidade:** Alta
- **Tabela:** Informações Básicas (INFO_BSICO)
- **Tipo Pessoa:** PF
- **Descrição:** Apaga o conteúdo do campo código do sexo por não pertencer aos domínios permitidos.
- **Objetivo:** Apagar o conteúdo do campo código do sexo.
- **Critério de Aplicação:** Executar em todos os registros que foram segregados como inconsistentes pela regra IBS.RV.1.
- **Lógica de Execução:** A regra apaga o conteúdo do campo CMPO_SEXO nos registros que foram segregados como inconsistentes.
- **Resultado:** nan

---

## Regra: Enriquecimento de nome social

- **Código:** IBS.RE.1
- **Tipo:** Enriquecimento
- **Criticidade:** Alta
- **Tabela:** Informações Básicas (INFO_BSICO)
- **Tipo Pessoa:** PF
- **Descrição:** Enriquece o campo nome social de pessoa física em fonte externa (RBRF), quando o campo no PSDC estiver vazio.
- **Objetivo:** Enriquecer o campo nome social na base RBRF, quando estiver vazio no PSDC.
- **Critério de Aplicação:** Executar em todos os registros com campo nome social vazio no PSDC.
- **Lógica de Execução:** A regra enriquece o campo CMPO_NOME_SOC com base na RBRF quando o campo estiver vazio no PSDC.
- **Resultado:** Sucesso: registros enriquecidos.
Falha: registro não encontrado na RBRF.
