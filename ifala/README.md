# IFala — ouvidoria estudantil do IFRN

Canal de reclamações do campus. Os usuários entram com login (matrícula e senha),
mas o nome do autor **não aparece** para a comunidade: só o painel administrativo
mostra quem enviou cada reclamação.

## Como rodar

1. Tenha o PostgreSQL rodando (ajuste usuário/senha em `model.py`).
2. `pip install -r requirements.txt`
3. `python app.py`
4. Acesse http://127.0.0.1:5000 , crie uma conta em `/cadastro` e entre.

O banco `campus` e as tabelas são criados automaticamente na primeira execução.
Bancos antigos são atualizados (colunas novas via `ALTER TABLE ... IF NOT EXISTS`).

## Antes de ir para produção

- Trocar `app.secret_key` e as credenciais do admin (`admin` / `1234`) por variáveis de ambiente.
- Validar quem pode se cadastrar (lista de matrículas ou e-mail institucional).
- Trocar a exclusão de reclamações (`GET /excluir/<id>`) por POST.
