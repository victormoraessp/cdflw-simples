# Base de Conhecimento para Geração de Regras de Negócio (EXEMPLO SINTÉTICO)

## Governança de Regras de Cadastro de Clientes

## Parâmetros de Chunking Recomendados

```json
{
  "chunk_size": 512,
  "chunk_overlap": 64,
  "unidade": "tokens"
}
```

## 1. Contexto e Propósito

Esta base de conhecimento orienta a geração de regras de cadastro para qualificação de dados de clientes (pessoa física e jurídica). Este arquivo é um exemplo sintético: nenhuma sigla aqui é real.

## 2. Sistema de Gestão

As regras são gerenciadas pelo CadFlow (aplicativo Power Apps).

## 3. Taxonomia e Definições Fundamentais

### 3.1 Estrutura de Dados

```json
[
  {"secao": "estrutura_de_dados", "conceito": "Bloco de Dados", "definicao": "Agrupamento temático de campos no sistema PSDC", "exemplos": ["Dados de Contato", "Dados Pessoais"]},
  {"secao": "estrutura_de_dados", "conceito": "Tabela de Dados", "definicao": "Tabela na base do sistema PSDC, identificada por sigla", "exemplos": ["Tabela Contato"]},
  {"secao": "estrutura_de_dados", "conceito": "Campo", "definicao": "Atributo da Tabela de Dados, identificado por uma sigla"},
  {"secao": "estrutura_de_dados", "conceito": "Prefixo da Regra", "definicao": "Abreviação de 3 caracteres que identifica a Tabela de Dados à qual a regra pertence", "exemplos": ["ICT (Tabela Contato)"]}
]
```

### 3.3 Papéis e Responsabilidades

```json
[
  {"secao": "papeis_e_responsabilidades", "papel": "Equipe de MDM", "responsabilidade": "Construção inicial das regras", "atua_no_status": "Em construção"},
  {"secao": "papeis_e_responsabilidades", "papel": "Equipe de Governança do Cadastro", "responsabilidade": "Analisa regras de todas as criticidades", "atua_no_status": "Em análise com Governança"}
]
```

## 4. Tipos de Regras

```json
[
  {"secao": "tipos_de_regra", "tipo": "Negócio", "funcao": "Agrupa todas as regras aplicadas a um conjunto de campos. É a primeira a ser criada.", "campos_obrigatorios_adicionais": []},
  {"secao": "tipos_de_regra", "tipo": "Validação", "funcao": "Verifica se o dado atende aos padrões técnicos de formato, domínios e negócio.", "campos_obrigatorios_adicionais": ["Exemplo", "Ação para dado válido", "Ação para dado inválido"]},
  {"secao": "tipos_de_regra", "tipo": "Enriquecimento", "funcao": "Recupera conteúdo do campo ou complementa o dado usando fontes internas e/ou externas.", "campos_obrigatorios_adicionais": []},
  {"secao": "tipos_de_regra", "tipo": "Limpeza", "funcao": "Sanitização do dado para corrigir erros sintáticos e de formatação.", "campos_obrigatorios_adicionais": []},
  {"secao": "tipos_de_regra", "tipo": "Retroalimentação", "funcao": "Garantir que o resultado da governança distribua a melhor informação.", "campos_obrigatorios_adicionais": []},
  {"secao": "tipos_de_regra", "tipo": "Regra Geral", "funcao": "Consolida aplicação para vários campos e Tabelas de Dados.", "campos_obrigatorios_adicionais": []}
]
```

## 5. Criticidade das Regras

```json
[
  {"secao": "criticidade", "nivel": "Baixa", "complexidade": "Baixa", "exemplo": "Validações de formato simples", "fluxo_aprovacao": ["Liderança Técnica", "Governança"]},
  {"secao": "criticidade", "nivel": "Média", "complexidade": "Média", "exemplo": "Enriquecimentos com fonte interna", "fluxo_aprovacao": ["Governança", "Gestores"]},
  {"secao": "criticidade", "nivel": "Alta", "complexidade": "Alta", "exemplo": "Regras de limpeza de campo", "impacto_de_falha": "Elevado", "fluxo_aprovacao": ["Governança", "Gestores"]},
  {"secao": "criticidade", "nivel": "Muito Alta", "complexidade": "Muito alta", "exemplo": "Exclusão em larga escala", "impacto_de_falha": "Grave", "fluxo_aprovacao": ["Governança", "Gestores", "Comissão"]}
]
```

## 6. Ciclo de Vida da Regra (Status)

```json
[
  {"secao": "ciclo_de_vida", "status": "Em construção", "descricao": "Primeiro estágio após a regra ser cadastrada"},
  {"secao": "ciclo_de_vida", "status": "Aprovada", "descricao": "Regra vigente, aprovada em todos os estágios aplicáveis"},
  {"secao": "ciclo_de_vida", "status": "Backlog", "descricao": "Regra em análise complementar"}
]
```

## 8. Campos Obrigatórios para Geração de Regras

```json
[
  {"secao": "campos_obrigatorios", "aplicavel_a": "TODAS as regras", "campo": "Critério de aplicação", "obrigatorio": true},
  {"secao": "campos_obrigatorios", "aplicavel_a": "TODAS as regras", "campo": "Lógica de execução", "obrigatorio": true},
  {"secao": "campos_obrigatorios", "aplicavel_a": "TODAS as regras", "campo": "Resultado", "obrigatorio": true},
  {"secao": "campos_obrigatorios", "aplicavel_a": "Apenas regras do tipo Validação", "campo": "Exemplo", "obrigatorio": true},
  {"secao": "campos_obrigatorios", "aplicavel_a": "Apenas regras do tipo Validação", "campo": "Ação para dado válido", "obrigatorio": true},
  {"secao": "campos_obrigatorios", "aplicavel_a": "Apenas regras do tipo Validação", "campo": "Ação para dado inválido", "obrigatorio": true}
]
```

## 9. Diretrizes para Geração de Regras pela IA

Ao gerar regras de negócio, a IA deve: (1) classificar o tipo; (2) atribuir criticidade; (3) preencher todos os campos obrigatórios; (4) associar à estrutura de dados correta; (5) definir o prefixo pela Tabela de Dados; (9) manter rastreabilidade no CadFlow.
