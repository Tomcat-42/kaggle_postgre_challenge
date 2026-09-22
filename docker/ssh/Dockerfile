FROM debian:bookworm-slim

ARG SSH_USER=appuser
ARG SSH_PASSWORD=appuser

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openssh-server \
        postgresql-client \
        sudo \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /var/run/sshd \
    && useradd -m -s /bin/bash "${SSH_USER}" \
    && echo "${SSH_USER}:${SSH_PASSWORD}" | chpasswd \
    && echo "PermitRootLogin no" >> /etc/ssh/sshd_config \
    && echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config

EXPOSE 22

CMD ["/usr/sbin/sshd", "-D"]
