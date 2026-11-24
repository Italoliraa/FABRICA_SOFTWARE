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
* Consultar barbeiros, dias de atendimento e horários livres;
* Realizar agendamentos;
* Visualizar seus agendamentos;
* Cancelar agendamentos.

### 💈 Barbeiro

* Visualizar sua agenda;
* Consultar informações dos atendimentos;
* Visualizar clientes agendados;
* Atualizar o status dos atendimentos.

### 🔐 Administrador

* Consultar um painel de faturamento, ocupação, serviços mais procurados e cancelamentos;
* Filtrar indicadores por período e exportar relatórios em CSV;
* O faturamento soma o preço registrado para serviços concluídos; o sistema não controla pagamentos;
* Cadastrar barbeiros;
* Editar e excluir barbeiros;
* Cadastrar serviços;
* Definir preço e duração dos serviços;
* Editar e excluir serviços;
* Configurar dias e horários de atendimento de cada barbeiro;
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

O sistema reserva o intervalo completo de cada serviço: agendamentos do mesmo barbeiro não podem se sobrepor, mesmo quando começam em horários diferentes. A confirmação é serializada no banco de dados para impedir que solicitações simultâneas reservem o mesmo intervalo. A duração usada na reserva fica registrada no agendamento, sem mudar quando o serviço for editado depois.

A disponibilidade do barbeiro também é validada por dia da semana e faixa de
horário. Quando o barbeiro não atende na data escolhida, o sistema informa os
dias de atendimento configurados. Quando um horário está ocupado, os horários
livres daquele dia são exibidos para o cliente.

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
* 🔑 Senhas protegidas com scrypt e migração de hashes antigos no login;
* 🛡️ Proteção CSRF em formulários e ações de escrita;
* 🔒 Chaves de sessão configuradas pelo ambiente, sem segredo fixo no código;
* ✅ Validação dos dados enviados;
* 🚫 Prevenção de horários conflitantes;
* 📱 Interface responsiva;
* 💬 Mensagens claras de erro e sucesso;
* ⚡ Tempo de resposta adequado;
* 🧩 Separação entre frontend, backend e banco de dados;
* 🌱 Versionamento utilizando Git e GitHub.

### Mudanças de segurança implementadas

* A chave fixa de sessão foi removida. Em desenvolvimento, uma chave aleatória
  temporária é gerada; em produção, `BARBERAGENDA_SECRET_KEY` é obrigatório.
* As senhas novas são armazenadas com scrypt. Hashes SHA-256 antigos são
  atualizados para scrypt depois de um login válido.
* Credenciais padrão de demonstração foram removidas. Um banco novo exige uma
  senha inicial de administrador configurada no ambiente; contas de exemplo
  podem ser criadas somente em desenvolvimento.
* Formulários que alteram dados validam CSRF. Sair da conta agora usa POST,
  não GET.
* O modo debug é restrito ao desenvolvimento; cookies de sessão recebem
  `HttpOnly`, `SameSite=Lax` e, em produção, `Secure`.
* Testes automatizados cobrem hashing, migração de senhas antigas, CSRF,
  configuração de produção e fluxos existentes.

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

* SQLite

### Ferramentas

* Git
* GitHub
* Visual Studio Code
* OpenCL (aceleracao opcional da filtragem de horarios)

### OpenCL

A filtragem dos horarios disponiveis usa OpenCL quando existe um dispositivo
e um driver OpenCL instalados. O sistema seleciona uma GPU quando disponivel
e usa a CPU caso contrario, sem alterar o resultado funcional da agenda.

Foram adicionadas as dependencias `numpy` e `pyopencl` no arquivo
`requirements.txt`. O `numpy` prepara os dados enviados ao dispositivo e o
`pyopencl` fornece a comunicacao entre Python e OpenCL.

Para instalar as dependencias:

```bash
pip install -r requirements.txt
```

### Configuração de segurança

Antes de inicializar um banco novo, configure `BARBERAGENDA_ADMIN_PASSWORD`
com uma senha de 12 a 128 caracteres. `BARBERAGENDA_ADMIN_EMAIL` pode definir
o e-mail inicial do administrador. Em desenvolvimento, `BARBERAGENDA_DEMO_PASSWORD`
é opcional e cria contas de exemplo com uma senha compartilhada; não configure
essa variável em produção.

Gere uma chave de sessão com:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Defina o resultado em `BARBERAGENDA_SECRET_KEY`. Em `APP_ENV=production`, a
chave é obrigatória, os cookies de sessão usam HTTPS e o modo de depuração é
desativado. Em desenvolvimento, se a chave não for definida, é gerada uma
chave temporária que invalida as sessões quando o processo reinicia.
O comando `python app.py` é apenas para desenvolvimento; em produção, use um
servidor WSGI/Socket.IO apropriado.

Senhas legadas em SHA-256 são verificadas e atualizadas para scrypt após um
login válido. Contas já existentes mantêm suas senhas; redefina qualquer senha
de demonstração conhecida antes de usar um banco antigo em produção.
Formulários POST, inclusive sair da conta, exigem token CSRF.

Execute os testes automatizados com:

```bash
python -m unittest discover -s tests -v
```

O suporte depende do driver OpenCL fornecido pelo fabricante da GPU/CPU. A
ausencia desse driver nao impede a inicializacao da aplicacao.

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
