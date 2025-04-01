from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pandas as pd
from datetime import datetime
from sklearn.ensemble import IsolationForest
from sqlalchemy import text
import sqlalchemy
import os
from dotenv import load_dotenv
from typing import Optional

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = sqlalchemy.create_engine(DATABASE_URL)

app = FastAPI()

class Transacao(BaseModel):
    id: Optional[int] = None
    cliente: str
    valor_transacao: float
    data: str
    status: str
    justificativa: Optional[str] = None

@app.get("/")
def root():
    return {"message": "AuditAI API online"}

@app.get("/relatorio")
def relatorio():
    try:
        query = "SELECT * FROM transacoes ORDER BY data DESC"
        df = pd.read_sql(query, engine)
        df['data'] = pd.to_datetime(df['data'])
        return df.to_dict(orient='records')
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auditoria")
def auditar_transacoes():
    try:
        import json
        with open("regras_compliance_auditai.json", "r", encoding="utf-8") as f:
            regras = json.load(f)

        df = pd.read_sql("""
            SELECT id, cliente, valor_transacao, data, status, justificativa
            FROM transacoes
            WHERE data >= NOW() - INTERVAL '30 days'
        """, engine)
        df['data'] = pd.to_datetime(df['data'])

        def aplicar_regras_compliance(row):
            violacoes = []
            for regra in regras:
                campo = regra["campo_relevante"]
                condicao = regra["condicao"]

                if campo == "valor_transacao" and condicao == "> 10000":
                    if row.get("valor_transacao", 0) > 10000 and not row.get("justificativa"):
                        violacoes.append(regra)

                elif campo == "status/data" and condicao == "pendente > 7 dias":
                    if row.get("status") == "Pendente":
                        data = pd.to_datetime(row.get("data"))
                        if (datetime.now() - data).days > 7:
                            violacoes.append(regra)

                elif campo == "cliente" and condicao == "cliente estrangeiro":
                    if "Ltd" in row.get("cliente", "") or "Inc" in row.get("cliente", ""):
                        violacoes.append(regra)

                elif campo == "justificativa" and condicao == "contém dado pessoal":
                    just = row.get("justificativa")
                    if just and isinstance(just, str):
                        just = just.lower()
                    else:
                        just = ""
                    if any(term in just for term in ["cpf", "nome", "rg", "email"]):
                        violacoes.append(regra)

            return violacoes

        df["violacoes_compliance"] = df.apply(lambda row: aplicar_regras_compliance(row), axis=1)

        resultado = df[["id", "cliente", "valor_transacao", "data", "status", "justificativa", "violacoes_compliance"]]
        return {"auditorias": resultado.to_dict(orient="records")}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transacao")
def inserir_transacao(transacao: Transacao):
    try:
        query = text("""
            INSERT INTO transacoes (cliente, valor_transacao, data, status, justificativa)
            VALUES (:cliente, :valor_transacao, :data, :status, :justificativa)
        """)
        with engine.connect() as connection:
            connection.execute(query, {
                "cliente": transacao.cliente,
                "valor_transacao": transacao.valor_transacao,
                "data": transacao.data,
                "status": transacao.status,
                "justificativa": transacao.justificativa
            })
        return {"mensagem": "Transação inserida com sucesso."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
