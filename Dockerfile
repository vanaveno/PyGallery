FROM golang:1.21-alpine AS builder
RUN apk add --no-cache gcc musl-dev

WORKDIR /app
# Kopírujeme vše včetně složky vendor
COPY . .

# Nechceme nic stahovat, použijeme vendor
ENV GOFLAGS="-mod=vendor"

# Hned kompilujeme
RUN CGO_ENABLED=1 GOOS=linux go build -o main .

FROM alpine:latest
RUN apk add --no-cache ca-certificates tzdata ffmpeg python3 py3-pip curl
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp && \
    chmod a+rx /usr/local/bin/yt-dlp

WORKDIR /root/
COPY --from=builder /app/main .
RUN mkdir -p media/movies media/pics
EXPOSE 8001
CMD ["./main"]