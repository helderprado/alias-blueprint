# Source-built Community server and client; both retain their AGPLv3 licenses.
FROM golang:1.24.8-bookworm@sha256:4ed690d6649d63c312b99a6120025ec79ce3b542968a37da53d6236c7c61a848 AS build
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
ADD --checksum=sha256:45521908307306e925c98d629e1c17d78c8b72b6ee242b1bfb1409f7d8ee5841 https://codeload.github.com/minio/minio/tar.gz/9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a /tmp/minio.tar.gz
ADD --checksum=sha256:95cd293c7119f16921a6dc515a1fb74a2227f19fd994b9c8b770a154e802ac44 https://codeload.github.com/minio/mc/tar.gz/7394ce0dd2a80935aded936b09fa12cbb3cb8096 /tmp/mc.tar.gz
RUN mkdir -p /src/minio /src/mc /out && \
    tar -xzf /tmp/minio.tar.gz --strip-components=1 -C /src/minio && \
    tar -xzf /tmp/mc.tar.gz --strip-components=1 -C /src/mc
WORKDIR /src/minio
RUN go mod download && go mod verify && go mod vendor && \
    go build -mod=vendor -tags kqueue -trimpath -buildvcs=false \
      -ldflags='-s -w -X github.com/minio/minio/cmd.Version=2025-10-15T17:29:55Z -X github.com/minio/minio/cmd.ReleaseTag=RELEASE.2025-10-15T17-29-55Z -X github.com/minio/minio/cmd.CommitID=9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a -X github.com/minio/minio/cmd.ShortCommitID=9e49d5e7a648 -X github.com/minio/minio/cmd.CopyrightYear=2025' \
      -o /out/minio .
WORKDIR /src/mc
RUN go mod download && go mod verify && go mod vendor && \
    go build -mod=vendor -tags kqueue -trimpath -buildvcs=false \
      -ldflags='-s -w -X github.com/minio/mc/cmd.Version=2025-08-13T08:35:41Z -X github.com/minio/mc/cmd.ReleaseTag=RELEASE.2025-08-13T08-35-41Z -X github.com/minio/mc/cmd.CommitID=7394ce0dd2a80935aded936b09fa12cbb3cb8096' \
      -o /out/mc .
COPY Dockerfile /src/Dockerfile
# Preserve the actual sources, vendored dependencies, Go runtime sources and recipe.
RUN cp /src/minio/LICENSE /out/LICENSE.minio && cp /src/mc/LICENSE /out/LICENSE.mc && \
    cp /usr/local/go/LICENSE /src/LICENSE.go && \
    cp -a /usr/local/go/src /src/go-runtime && \
    tar -czf /out/corresponding-source.tar.gz -C /src .

FROM python:3.11.11-slim-bookworm@sha256:081075da77b2b55c23c088251026fb69a7b2bf92471e491ff5fd75c192fd38e5
LABEL org.opencontainers.image.title="ALIAS optional MinIO Community server and client" \
      org.opencontainers.image.version="RELEASE.2025-10-15T17-29-55Z" \
      org.opencontainers.image.revision="9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a" \
      org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"
COPY --from=build /out/minio /out/mc /usr/local/bin/
COPY --from=build /out/LICENSE.minio /out/LICENSE.mc /out/corresponding-source.tar.gz /usr/share/minio/
ENV HOME=/tmp
USER 1000:1000
EXPOSE 9000 9001
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--console-address", ":9001"]
