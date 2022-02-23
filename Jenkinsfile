// in the form 'server/group/project/image:tag'
IMAGE = "registry.quokka.ninja/ccfs/xsautomate-actions/reconcile-snow-prtg"
VERSION = '0.1.0'
K8S_PATH = 'kubernetes/reconcile-snow-prtg-deployment.yaml'
KANIKO_TAG = 'v1.6.0-debug'
KUBECTL_TAG = '1.19.16'
// name of secret that contains registry credentials
REG_CRED = 'gitlab-cr'

pipeline {
    triggers {
        githubPush()
    }
    agent {
        kubernetes {
            inheritFrom 'default'
            yaml """
                apiVersion: v1
                kind: Pod
                spec:
                  containers:
                  - name: kaniko
                    image: gcr.io/kaniko-project/executor:$KANIKO_TAG
                    command:
                    - sleep
                    args:
                    - 99d
                    volumeMounts:
                    - name: registry-config
                      mountPath: /kaniko/.docker
                  - name: kubectl
                    image: bitnami/kubectl:$KUBECTL_TAG
                    command:
                    - sleep
                    args:
                    - 99d
                  volumes:
                  - name: registry-config
                    secret:
                      secretName: $REG_CRED
                      items:
                      - key: .dockerconfigjson
                        path: config.json
                  securityContext:
                    runAsUser: 0
            """
        }
    }
    stages {
        stage('Build and Push Non-Prod Image') {
            when {
                not {
                    branch 'main'
                }
            }
            steps {
                container('kaniko') {
                    sh "/kaniko/executor -c . --destination=$IMAGE:${env.GIT_BRANCH}"
                }
            }

        }
        stage('Build and Push Production Image') {
            when {
                branch 'main'
            }
            steps {
                container('kaniko') {
                    sh "/kaniko/executor -c . --destination=$IMAGE:latest --destination=$IMAGE:$VERSION"
                }
            }
        }
        stage('Update Production Deployment') {
            when {
                branch 'main'
            }
            steps {
                container('kubectl') {
                    sh """
                        if kubectl get -f $K8S_PATH
                        then
                            kubectl apply -f $K8S_PATH
                            kubectl rollout restart -f $K8S_PATH
                        else
                            kubectl apply -f $K8S_PATH
                        fi
                    """
                }
            }
        }
    }
}