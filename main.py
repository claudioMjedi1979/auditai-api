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
        df = pd.read_sql("""
            SELECT id, cliente, valor_transacao, data, status, justificativa
            FROM transacoes
            WHERE data >= NOW() - INTERVAL '30 days'
        """, engine)

        def regras_basicas(row):
            violacoes = []
            if row['valor_transacao'] > 10000 and not row['justificativa']:
                violacoes.append("Transação > R$10.000 sem justificativa")
            if row['status'] == 'Pendente' and (datetime.now() - row['data']).days > 7:
                violacoes.append("Status pendente há mais de 7 dias")
            return violacoes

        df['data'] = pd.to_datetime(df['data'])
        df['violacoes'] = df.apply(regras_basicas, axis=1)

        modelo_ia = IsolationForest(contamination=0.05)
        valores = df[['valor_transacao']].fillna(0)
        df['anomalia'] = modelo_ia.fit_predict(valores)
        df['anomalia'] = df['anomalia'].apply(lambda x: 'Sim' if x == -1 else 'Não')

        resultado = df[df['violacoes'].apply(len) > 0].copy()
        resultado['violacoes'] = resultado['violacoes'].astype(str)
        return {"violacoes": resultado.to_dict(orient='records')}
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