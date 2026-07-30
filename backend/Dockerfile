# Imagem do backend do Conciliador Bancário (API HTTP sobre o pipeline de src/).
#
# Build e execução local:
#   docker build -t conciliador-api ./backend
#   docker run --rm -p 8000:8000 -e CORS_ORIGINS=http://localhost:3000 conciliador-api

FROM python:3.12-slim

# bytecode em disco não ajuda num container; log sem buffer aparece na hora.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Só as dependências de execução (streamlit e pytest ficam de fora de propósito).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# O pipeline e a camada HTTP. `src/assets/painel_visual/` entra junto — são os
# XML/PNG/SVG lidos em runtime para desenhar os 5 cards do painel executivo
# (ver src/exportador_shapes.py). Sem eles a planilha sai sem o painel.
COPY src/ ./src/
COPY api/ ./api/

# O código fica somente-leitura; tudo que é escrito vai para /tmp.
ENV CONCILIADOR_RUNTIME_DIR=/tmp/conciliador-execucoes \
    CONCILIADOR_LOG_DIR=/tmp/conciliador-logs \
    PORT=8000

RUN useradd --create-home --uid 10001 conciliador
USER conciliador

EXPOSE 8000

# $PORT é definido pelo host (o Render injeta o dele); o default cobre o uso local.
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
