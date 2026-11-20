# Use uma imagem base oficial do Python
FROM python@sha256:081075da77b2b55c23c088251026fb69a7b2bf92471e491ff5fd75c192fd38e5

# Copie o arquivo de requisitos para o diretório de trabalho
COPY requirements.txt .

# Instale as dependências do projeto
RUN pip install --no-cache-dir --no-deps --require-hashes --only-binary=:all: -r requirements.txt

