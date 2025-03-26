# AuditAI - API

API de análise de transações com IA e validações de compliance.

## Rodar localmente
```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

## Deploy no Render
1. Suba esta pasta para um repositório no GitHub
2. Acesse https://render.com
3. Crie um novo Web Service
4. Selecione este repositório
5. Configure:
   - Start command: `uvicorn main:app --host=0.0.0.0 --port=$PORT`
   - Build command: `pip install -r requirements.txt`
   - Environment: Python 3.9+
6. Adicione a variável `DATABASE_URL` com sua string do Supabase