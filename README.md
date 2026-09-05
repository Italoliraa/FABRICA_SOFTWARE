# 💈 BarberAgenda

### Sistema Full Stack de Agendamento para Barbearias

> **Menos mensagens. Menos conflitos. Mais organização.**

O **BarberAgenda** é uma aplicação web Full Stack desenvolvida para facilitar o processo de agendamento em barbearias.

A plataforma conecta **clientes, barbeiros e administradores** em um único ambiente, permitindo que os clientes consultem serviços, escolham seu barbeiro, visualizem horários disponíveis e realizem seus agendamentos de forma simples.

Para a barbearia, o sistema centraliza a agenda e facilita o acompanhamento dos atendimentos.

---

## 🎯 O problema

Em muitas barbearias, os agendamentos ainda são realizados através de **WhatsApp, ligações ou anotações manuais**.

Embora sejam métodos simples, eles podem gerar conflitos de horários, demora nas respostas, dificuldade para acompanhar a agenda e uma grande quantidade de mensagens para organizar.

Imagine a seguinte situação:

> Um cliente envia uma mensagem perguntando se existe horário às 15h.
> Enquanto aguarda uma resposta, outro cliente solicita o mesmo horário.
> O barbeiro está atendendo e ninguém consegue confirmar imediatamente a disponibilidade.

Esse tipo de situação pode resultar em **conflitos de agenda, horários ociosos e uma experiência ruim para o cliente**.

### 💡 Nossa solução

O BarberAgenda centraliza todo o processo de agendamento.

O cliente consegue:

**Escolher o serviço → Escolher o barbeiro → Escolher a data → Visualizar horários disponíveis → Agendar**

Enquanto isso, o barbeiro consegue acompanhar sua agenda e o administrador possui uma visão geral dos agendamentos da barbearia.

---

## 🚀 Funcionalidades

### 👤 Cliente

* Consultar serviços disponíveis;
* Visualizar preço e duração dos serviços;
* Selecionar barbeiro;
* Consultar horários disponíveis;
* Realizar agendamentos;
* Visualizar seus agendamentos;
* Cancelar agendamentos.

### 💈 Barbeiro

* Visualizar sua agenda;
* Consultar informações dos atendimentos;
* Visualizar clientes agendados;
* Atualizar o status dos atendimentos.

### 🔐 Administrador

* Cadastrar barbeiros;
* Editar e excluir barbeiros;
* Cadastrar serviços;
* Definir preço e duração dos serviços;
* Editar e excluir serviços;
* Configurar horários disponíveis;
* Visualizar os agendamentos da barbearia.

---

## 📅 Fluxo de um agendamento

```text
                    CLIENTE
                       │
                       ▼
              Escolhe o serviço
                       │
                       ▼
              Escolhe o barbeiro
                       │
                       ▼
                Escolhe a data
                       │
                       ▼
           Consulta horários livres
                       │
                       ▼
             Confirma o agendamento
                       │
                       ▼
                ┌─────────────┐
                │ BarberAgenda│
                └──────┬──────┘
                       │
                       ▼
             Agenda do barbeiro
```

O sistema possui uma regra importante: **um mesmo barbeiro não pode possuir dois agendamentos para o mesmo horário**, evitando conflitos na agenda.

---

## 🔄 Status dos atendimentos

Cada atendimento pode assumir diferentes estados:

| Status                | Descrição                       |
| --------------------- | ------------------------------- |
| 🟡 **Agendado**       | Atendimento criado pelo cliente |
| 🔵 **Confirmado**     | Atendimento confirmado          |
| 🟠 **Em atendimento** | Cliente está sendo atendido     |
| 🟢 **Concluído**      | Atendimento finalizado          |
| 🔴 **Cancelado**      | Atendimento cancelado           |

---

## 🏗️ Arquitetura

O projeto utiliza uma arquitetura dividida em três principais camadas:

```text
┌──────────────────────────┐
│        FRONTEND          │
│   Interface do usuário   │
└────────────┬─────────────┘
             │
             │ HTTP / API
             ▼
┌──────────────────────────┐
│         BACKEND          │
│   Regras de negócio/API  │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│       BANCO DE DADOS     │
│      Persistência        │
└──────────────────────────┘
```

Essa separação facilita a organização, manutenção e evolução do sistema.

---

## 🔒 Segurança e qualidade

O BarberAgenda foi planejado considerando alguns requisitos importantes:

* 🔐 Autenticação de usuários;
* 👥 Controle de acesso por perfil;
* ✅ Validação dos dados enviados;
* 🚫 Prevenção de horários conflitantes;
* 📱 Interface responsiva;
* 💬 Mensagens claras de erro e sucesso;
* ⚡ Tempo de resposta adequado;
* 🧩 Separação entre frontend, backend e banco de dados;
* 🌱 Versionamento utilizando Git e GitHub.

---

## 🛠️ Tecnologias

> As tecnologias abaixo serão definidas e atualizadas conforme o desenvolvimento do projeto.

### Frontend

* HTML5
* CSS3
* JavaScript
* [Framework escolhido pela equipe]

### Backend

* [Tecnologia escolhida pela equipe]
* API REST

### Banco de dados

* [Banco escolhido pela equipe]

### Ferramentas

* Git
* GitHub
* Visual Studio Code

---

## 🎓 Projeto acadêmico

O BarberAgenda está sendo desenvolvido como projeto acadêmico da disciplina de **Fábrica de Software**, no curso de **Ciência da Computação — turma 8NB**.

O projeto tem como foco aplicar, na prática, conceitos de:

* Desenvolvimento Full Stack;
* Engenharia de Software;
* Banco de Dados;
* APIs;
* Autenticação;
* Regras de negócio;
* Metodologias ágeis;
* Git e GitHub;
* Testes de software.

---

## 👨‍💻 Equipe

| Integrante                            |
| ------------------------------------- |
| **Italo Jocemar Fernandes de Lira**   |
| **Pedro Dutra de Albuquerque Macêdo** |
| **Breno Miguel Soares da Silva**      |
| **Wesley**                            |

---

## 📌 Status do projeto

🚧 **Em desenvolvimento**

O projeto está sendo desenvolvido de forma incremental, seguindo um Product Backlog e priorizando inicialmente as funcionalidades essenciais para o funcionamento do sistema.

---

## 🔮 Possíveis evoluções

Após a implementação da versão inicial, algumas funcionalidades poderão ser consideradas para futuras versões:

* 📲 Notificações de agendamento;
* 💬 Integração com WhatsApp;
* 📊 Dashboard com indicadores da barbearia;
* 📈 Relatórios de atendimentos;
* 👥 Histórico de clientes;
* ⭐ Avaliação dos serviços;
* 💳 Pagamento online.

Essas funcionalidades não fazem parte do escopo principal da primeira versão e poderão ser desenvolvidas posteriormente.

---

## 📁 Documentação do projeto

A documentação completa contém informações sobre:

* Definição do problema;
* Objetivos;
* Público-alvo;
* Requisitos funcionais;
* Requisitos não funcionais;
* Casos de uso;
* Product Backlog;
* Cronograma;
* Arquitetura e desenvolvimento.

---

## 🔗 Repositório

**GitHub:**
https://github.com/Italoliraa/FABRICA_SOFTWARE

---

### 💈 BarberAgenda

**Sua agenda. Seus clientes. Seu controle.**

> Transformando a agenda da barbearia em uma experiência simples, organizada e digital.
