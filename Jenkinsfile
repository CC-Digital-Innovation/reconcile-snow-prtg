// in the form 'server/group/project/image:tag'
IMAGE = "registry.quokka.ninja/ccfs/xsautomate-actions/reconcile-snow-prtg"
VERSION = '0.1.0'
K8S_PATH = 'kubernetes/reconcile-snow-prtg-deployment.yaml'

pipeline {
    triggers {
        githubPush()
    }
    agent {
        kubernetes {
            inheritFrom 'kaniko-and-kubectl'
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