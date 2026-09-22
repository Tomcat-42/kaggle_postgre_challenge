FROM debian:bookworm-slim

ARG SSH_USER=appuser
ARG SSH_PASSWORD=appuser
ARG PG_PASSWORD=appuser

ENV PG_USER=${SSH_USER}
ENV PG_PASSWORD=${PG_PASSWORD}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openssh-server \
        postgresql \
        sudo \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /var/run/sshd \
    && useradd -m -s /bin/bash "${SSH_USER}" \
    && echo "${SSH_USER}:${SSH_PASSWORD}" | chpasswd \
    && echo "PermitRootLogin no" >> /etc/ssh/sshd_config \
    && echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config

# Create the application role once, using the cluster the postgresql package
# already initialized during install, then leave it stopped for the entrypoint.
RUN service postgresql start \
    && su postgres -c "psql --command=\"CREATE USER ${SSH_USER} WITH SUPERUSER CREATEDB PASSWORD '${PG_PASSWORD}';\"" \
    && service postgresql stop

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22

CMD ["/entrypoint.sh"]
