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

# Carrega variáveis do .env
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# Cria engine de conexão
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

        def gerar_violacoes(row):
            violacoes = []

            if row['valor_transacao'] > 10000 and not row['justificativa']:
                violacoes.append({
                    "codigo": "V002",
                    "tipo": "Justificativa Ausente",
                    "descricao": "Valor elevado sem justificativa cadastrada",
                    "explicacao": "Transações acima de R$10.000 exigem justificativa para fins de auditoria e conformidade.",
                    "recomendacao": "Inserir uma justificativa válida para manter a rastreabilidade e aderência à LGPD (Art. 6º - Princípio da prestação de contas)."
                })

            if row['status'] == 'Pendente' and (datetime.now() - row['data']).days > 7:
                violacoes.append({
                    "codigo": "V001",
                    "tipo": "Prazo",
                    "descricao": "Status 'Pendente' há mais de 7 dias",
                    "explicacao": "Transações pendentes por muito tempo podem indicar atrasos no processo de aprovação, riscos operacionais ou falha de atualização de sistema.",
                    "recomendacao": "Revisar com a equipe financeira ou atualizar o status, mantendo os dados em conformidade com boas práticas de controle."
                })

            return violacoes

        df['data'] = pd.to_datetime(df['data'])
        df['violacoes_detalhadas'] = df.apply(gerar_violacoes, axis=1)

        modelo_ia = IsolationForest(contamination=0.05)
        valores = df[['valor_transacao']].fillna(0)
        df['anomalia_flag'] = modelo_ia.fit_predict(valores)

        def gerar_anomalia(row):
            return {
                "presente": row['anomalia_flag'] == -1,
                "descricao": "Esta transação apresentou padrão fora do comum." if row['anomalia_flag'] == -1 else "Esta transação não apresentou padrões anômalos segundo o modelo de IA.",
                "metodologia": "Detecção com algoritmo Isolation Forest sobre o histórico recente.",
                "observacao": "Mesmo sem anomalias matemáticas, violação de regras de compliance ainda pode existir."
            }

        df['anomalia_detalhada'] = df.apply(gerar_anomalia, axis=1)

        def gerar_conformidade_lgpd(row):
            return {
                "risco_dados": "Baixo",
                "observacao": "Sem dados sensíveis identificáveis nesta transação.",
                "boas_praticas": [
                    "Evite armazenar CPF, RG ou dados pessoais diretamente.",
                    "Inclua justificativas em transações de valor para fins de auditoria legal.",
                    "Mantenha dados atualizados e com finalidade clara, conforme Art. 6 da LGPD."
                ]
            }

        df['conformidade_lgpd'] = df.apply(gerar_conformidade_lgpd, axis=1)

        resultado = df[['id', 'cliente', 'valor_transacao', 'data', 'status', 'justificativa', 'violacoes_detalhadas', 'anomalia_detalhada', 'conformidade_lgpd']]
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

