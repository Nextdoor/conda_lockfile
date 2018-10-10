FROM debian:stretch

RUN mkdir /app
WORKDIR /app
ENV CONDA_ROOT /var/lib/conda

RUN apt-get update && \
    apt-get install --yes bzip2 curl libc6 libc6-dev libc-dev gcc net-tools && \
    apt-get autoclean

RUN curl https://repo.continuum.io/miniconda/Miniconda3-4.5.11-Linux-x86_64.sh > miniconda.sh
RUN bash miniconda.sh -b -f -p $CONDA_ROOT
ADD build_lockfile.sh .

ENTRYPOINT ["./build_lockfile.sh"]
