# xsautomate-actions

This provides a few functions to automate some actions between ServiceNow and PRTG.

Using PYSNOW, PRTG's API, and FastAPI, this program can:
* Initialize all devices from ServiceNow CMDB into a specific tree structure with pre-populated location, service url, ip address, icons, tags, priorities, and credentials.
* Reconciles company and site specific devices between ServiceNow and PRTG
* Reconcile all PRTG managed devices on ServiceNow and PRTG

## Table of Contents

* [Getting Started](#getting-started)
    * [ServiceNow Requirements](#servicenow-requirements)
    * [PRTG Requirements](#prtg-requirements)
    * [Local Requirements](#local-requirements)
    * [Installation](#installation)
    * [Usage](#usage)
        * [Docker](#docker)
        * [Kubernetes](#kubernetes)
* [TODOs](#todos)
* [Author](#author)
* [License](#license)

## Getting Started

### ServiceNow Requirements

Records and the fields required to initialize:

_`[R]` stands for a field that is a reference to another table_

_Names in parentheses represent its ServiceNow internal name. If name is missing, it is likely the same as the label._

* Company(core_company) - Name
* Country(u_country) - Name
* Location(cmn_location) - Name, Company`[R]`, Street, City, State, Country`[R]`
* Manufacturer - Name
* Devices(cmdb_ci) - Company`[R]`, Status(install_status), Location`[R]`, Category(u_category), Used For(u_used_for), CC Type(u_cc_type), Priority, Credential Type, Host Name(u_host_name), IP Address, Manufacturer`[R]`, Model Number, PRTG Implementation(u_prtg_implementation), PRTG Instrumentation(u_prtg_instrumentation), Username, Password(u_fs_password)
    * _`u_category` is a type to categorize the type of the device, e.g. server, network, backup, etc_
    * _`u_cc_type` is a type used to filter any out of scope devices_
    * _`install_status` is a type used to filter installed/active devices_
    * _`u_fs_password` is a password2 type field that can be decrypted_
    * _`u_prtg_implementation` is a flag used to recognize if a device is monitored on PRTG_
    * _`u_prtg_instrumentation` is a flag used to separate CC devices from customer managed devices. True = CC Infrastructure_
 
 In order to add credentials to PRTG devices, an API to decrypt u_fs_password is required.

### PRTG Requirements

* Local probe setup
* Add a group at local probe root. This is used as a template.
* Add a device at local probe root (not under group template). This is also used as a template.
    * Switch off inheritance for all credentials that does not inherit from group.

### Local Requirements

* Docker
    * _Note: Developed using Docker version 20.10.8, but was not tested with any other version._

or

* Kubernetes
    * Kubernetes cluster
    * [kubectl](https://kubernetes.io/docs/tasks/tools/) configured to cluster
        * _Note: Developed using version 1.19.16, but was not tested with any other version._

### Installation

Download code from GitHub:

```bash
git clone https://github.com/CC-Digital-Innovation/reconcile-snow-prtg.git
```

* or download the [zip](https://github.com/CC-Digital-Innovation/reconcile-snow-prtg/archive/refs/heads/main.zip)

### Usage

#### Docker

* Before the application can run, the configuration and docker-compose files must be decrypted using [sops](https://github.com/mozilla/sops). The required key file needs to be in the appropriate location.
    ```bash
    sops -d encrypted.ini > config.ini
    sops -d docker-compose.encrypted.yml > docker-compose.yml
    ```
* This container uses [Caddy-Docker-Proxy](https://github.com/lucaslorentz/caddy-docker-proxy) as a reverse proxy. Here is the [gist](https://gist.github.com/jonnyle2/e78b2803d1da709b8c5153a1248c4327). Save it in a separate directory and edit the domain name. Then,
    * Create the network:
    ```bash
    docker network create caddy
    ```
    * Start up the container:
    ```bash
    docker-compose up -d
    ```
* Edit the config.ini.example file and rename (remove .example).
* Edit the docker-compose.yml.example file and rename (remove .example).
* Start up the container:
```bash
docker-compose up -d
```
* FastAPI features documentation and schemas of the api, served at `/docs` or `/redocs`
* To have a recurring check, [Ofelia](https://github.com/mcuadros/ofelia) is used to schedule the job. Here is the [gist](https://gist.github.com/jonnyle2/d4d2859ea444e33a1c0cb06b44eb36d7). Save it in a separate directory, edit the domain name for the command, and use the same line as before to start up the container.
<hr/>

#### Kubernetes

The Kubernetes deployment will still need the container image from a container registry so build and push that first.

For example, using a local Docker to push to DockerHub:
```bash
docker build -t ccfs/reconcile-snow-prtg .
docker push ccfs/reconcile-snow-prtg
```
If not logged in (from CLI), run `docker login` before pushing.

The project will be deployed as a Deployment, but will need a Service and Ingress in order to be available to the public. For automatic HTTPS, [cert-manager](https://cert-manager.io/docs/) and [Let's Encrypt](https://letsencrypt.org/) can be used. An Ingress Controller will also need to be added (in the case of K3s, traefik is created and used by default).

`reconcile-snow-prtg-deployment.yaml` is already in the [repo](https://github.com/CC-Digital-Innovation/reconcile-snow-prtg/blob/main/kubernetes/reconcile-snow-prtg-deployment.yaml).

`reconcile-snow-prtg-service.yaml`
```yaml
apiVersion: v1
kind: Service
metadata:
  labels:
    io.kompose.service: reconcile-snow-prtg
  name: reconcile-snow-prtg
spec:
  ports:
  - port: 80
    protocol: TCP
  selector:
    io.kompose.service: reconcile-snow-prtg
```
* The `spec.selector` can by anything, but must be the same as the labels defined in the deployment. Here, the `metadata.labels` was chosen by [Kompose](https://kompose.io/).

`reconcile-snow-prtg-ingress.yaml`
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
    traefik.ingress.kubernetes.io/redirect-entry-point: https
    traefik.ingress.kubernetes.io/redirect-permanent: "true"
    traefik.ingress.kubernetes.io/rewrite-target: /
  name: reconcile-snow-prtg
spec:
  ingressClassName: traefik
  rules:
  - host: myhost.com
    http:
      paths:
      - backend:
          serviceName: reconcile-snow-prtg
          servicePort: 80
        path: /xsautomate
        pathType: Prefix
  tls:
  - hosts:
    - myhost.com
    secretName: reconcile-snow-prtg-cert
```
A few things to highlight in the Ingress:
* The cluster, certificate issuer was already [created](https://cert-manager.io/docs/configuration/acme/#creating-a-basic-acme-issuer) and is named `letsencrypt`. Adding it to the `metadata.annotations` and `spec.tls` will configure it to automatically provide TLS support.
* Traefik's Ingress Controller provides useful annotations like HTTP->HTTPS redirects and path rewrites, which is stripping the extra path (in this case `/xsautomate`) for the interals to use properly).

All manifests can be created using `kubectl apply -f <filename>`.

In this case:
```bash
kubectl apply -f reconcile-snow-prtg-deployment.yaml,reconcile-snow-prtg-service.yaml,reconcile-snow-prtg-ingress.yaml
```

## TODOs
* Create ServiceNow ticket for each customer when there are issues
* Functions to respond to tickets
* Weekly digest to include tickets created, pending, and resolved
* Service Catalog option for engineers to request any of the features

## Author
* Jonny Le <<jonny.le@computacenter.com>>

## License
MIT License

Copyright (c) 2021 Computacenter Digital Innovation

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
