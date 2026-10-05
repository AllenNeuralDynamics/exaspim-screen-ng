# hash:sha256:477083bdc51a1db7ab0fde07f5986c90969d9e8f02ff81485111a894638bce59
ARG REGISTRY_HOST
FROM $REGISTRY_HOST/codeocean/code-server-python-extensions-pack:v5.0

ARG DEBIAN_FRONTEND=noninteractive
ARG GIT_ASKPASS
COPY git-ask-pass /

RUN pip install -U --no-cache-dir \
    "exaspim-screen-ng @ git+https://github.com/AllenNeuralDynamics/exaspim-screen-ng@v0.1.0"
