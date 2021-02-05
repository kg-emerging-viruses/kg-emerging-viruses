pipeline {
    agent any

    triggers{
        cron('H H 1 1-12 *')
    }

    environment {
        BUILDSTARTDATE = sh(script: "echo `date +%Y%m%d`", returnStdout: true).trim()
        S3PROJECTDIR = 'kg-covid-19' // no trailing slash

        // Distribution ID for the AWS CloudFront for this bucket
        // used solely for invalidations
        AWS_CLOUDFRONT_DISTRIBUTION_ID = 'EUVSWXZQBXCFP'
    }

    options {
        timestamps()
    }
    stages {
        // Very first: pause for a minute to give a chance to
        // cancel and clean the workspace before use.
        stage('Ready and clean') {
            steps {
                // Give us a minute to cancel if we want.
                sleep time: 1, unit: 'MINUTES'
                cleanWs()
            }
        }

        stage('Initialize') {
            steps {
                // Start preparing environment.
                parallel(
                        "Report": {
                            sh 'env > env.txt'
                            sh 'echo $BRANCH_NAME > branch.txt'
                            sh 'echo "$BRANCH_NAME"'
                            sh 'cat env.txt'
                            sh 'cat branch.txt'
                            sh "echo $BUILDSTARTDATE > dow.txt"
                            sh "echo $BUILDSTARTDATE"
                        })
            }
        }

        stage('Build kg_covid_19') {
            steps {
                dir('./gitrepo') {
                    git(
                            url: 'https://github.com/Knowledge-Graph-Hub/kg-covid-19',
                            branch: env.BRANCH_NAME
                    )
                    sh '/usr/bin/python3.8 -m venv venv'
                    sh '. venv/bin/activate'
                    sh './venv/bin/pip install .'
                }
            }
        }

        stage('Download') {
            steps {
                dir('./gitrepo') {
                    script {
                        def run_py_dl = sh(
                            script: '. venv/bin/activate && python3.8 run.py download', returnStatus: true
                        )
                        if (run_py_dl == 0) {
                            if (env.BRANCH_NAME != 'master') { // upload raw to s3 if we're on correct branch
                                echo "Will not push if not on correct branch."
                            } else {
                                withCredentials([file(credentialsId: 's3cmd_kg_hub_push_configuration', variable: 'S3CMD_CFG')]) {
                                    sh 's3cmd -c $S3CMD_CFG --acl-public --mime-type=plain/text --cf-invalidate put -r data/raw s3://kg-hub-public-data/$S3PROJECTDIR/'
                                }
                            }
                        } else { // 'run.py download' failed - let's try to download last good copy of raw/ from s3 to data/
                            withCredentials([file(credentialsId: 's3cmd_kg_hub_push_configuration', variable: 'S3CMD_CFG')]) {
                                sh 'rm -fr data/raw || true;'
                                sh 'mkdir -p data/raw || true'
                                sh 's3cmd -c $S3CMD_CFG --acl-public --mime-type=plain/text get -r s3://kg-hub-public-data/$S3PROJECTDIR/raw/ data/raw/'
                            }
                        }
                    }
                }
            }
        }

        stage('Transform') {
            steps {
                dir('./gitrepo') {
                    sh 'env'
                    sh '. venv/bin/activate && env && python3.8 run.py transform'
                }
            }
        }

        stage('Merge') {
            steps {
                dir('./gitrepo') {
                    sh '. venv/bin/activate && python3.8 run.py merge -y merge_jenkins.yaml'
                    sh 'env'
                    sh 'cp merged_graph_stats.yaml merged_graph_stats_$BUILDSTARTDATE.yaml'
                    sh 'tar -rvf data/merged/merged-kg.tar merged_graph_stats_$BUILDSTARTDATE.yaml'
                }
            }
        }

        stage('Make blazegraph journal'){
            steps {
                dir('./gitrepo/blazegraph') {
                        git(
                                url: 'https://github.com/balhoff/blazegraph-runner.git',
                                branch: 'master'
                        )
                        sh 'sbt stage'
                        sh 'pigz -d ../data/merged/merged-kg.nt.gz'
                        sh 'export JAVA_OPTS=-Xmx128G && ./target/universal/stage/bin/blazegraph-runner load --informat=ntriples --journal=../merged-kg.jnl --use-ontology-graph=true ../data/merged/merged-kg.nt'
                        sh 'pigz ../merged-kg.jnl'
                        sh 'pigz ../data/merged/merged-kg.nt'
                }
            }
        }

        stage('Publish') {
            steps {
                dir('./gitrepo') {
                    script {
                        // code for building s3 index files
                        sh 'git clone https://github.com/justaddcoffee/go-site.git'
                        // fail early if there's going to be a problem installing these
                        sh '. venv/bin/activate && ./venv/bin/pip install awscli pystache boto3'

                        // make sure we aren't going to clobber existing data
                        withCredentials([file(credentialsId: 's3cmd_kg_hub_push_configuration', variable: 'S3CMD_CFG')]) {
                            REMOTE_BUILD_DIR_CONTENTS = sh (
                                script: 's3cmd -c $S3CMD_CFG ls s3://kg-hub-public-data/$S3PROJECTDIR/$BUILDSTARTDATE/',
                                returnStdout: true
                            ).trim()
                            echo "REMOTE_BUILD_DIR_CONTENTS (THIS SHOULD BE EMPTY): '${REMOTE_BUILD_DIR_CONTENTS}'"
                            if("${REMOTE_BUILD_DIR_CONTENTS}" != ''){
                                echo "Will not overwrite existing remote S3 directory: $S3PROJECTDIR/$BUILDSTARTDATE"
                                sh 'exit 1'
                            } else {
                                echo "remote directory $S3PROJECTDIR/$BUILDSTARTDATE is empty, proceeding"
                            }
                        }

                        if (env.BRANCH_NAME != 'master') {
                            echo "Will not push if not on correct branch."
                        } else {
                            withCredentials([
					            file(credentialsId: 's3cmd_kg_hub_push_configuration', variable: 'S3CMD_CFG'),
					            file(credentialsId: 'aws_kg_hub_push_json', variable: 'AWS_JSON'),
					            string(credentialsId: 'aws_kg_hub_access_key', variable: 'AWS_ACCESS_KEY_ID'),
					            string(credentialsId: 'aws_kg_hub_secret_key', variable: 'AWS_SECRET_ACCESS_KEY')]) {
                                //
                                // make $BUILDSTARTDATE/ directory and sync to s3 bucket
                                //
                                sh 'mkdir $BUILDSTARTDATE/'
                                sh 'cp -p data/merged/merged-kg.nt.gz $BUILDSTARTDATE/kg-covid-19.nt.gz'
                                sh 'cp -p data/merged/merged-kg.tar.gz $BUILDSTARTDATE/kg-covid-19.tar.gz'
                                sh 'cp -p merged-kg.jnl.gz $BUILDSTARTDATE/kg-covid-19.jnl.gz'
                                // transformed data
                                sh 'rm -fr data/transformed/.gitkeep'
                                sh 'cp -pr data/transformed $BUILDSTARTDATE/'
                                sh 'cp -pr data/raw $BUILDSTARTDATE/'
                                sh 'cp Jenkinsfile $BUILDSTARTDATE/'
                                // stats dir
                                sh 'mkdir $BUILDSTARTDATE/stats/'
                                sh 'cp -p *_stats.yaml $BUILDSTARTDATE/stats/'
                                sh 'cp templates/README.build $BUILDSTARTDATE/README'

                                // make local $S3PROJECTDIR
                                sh 'mkdir $S3PROJECTDIR'
                                sh 'cp templates/README.toplevel $S3PROJECTDIR/README'
                                // add dir for existing builds so they are indexed
                                // do an s3cmd ls for our project subdir, for each existing build make a local dir in $S3PROJECTDIR
                                sh "for dir in `s3cmd ls s3://kg-hub-public-data/kg-covid-19/ | grep '\\/\$' | awk '{print \$NF}' | grep -w -v -E 'raw|current' | xargs -n1 basename`; do mkdir -p $S3PROJECTDIR/\$dir; done"
                                // now make two dirs, $BUILDSTARTDATE and current/, both with the same contents
                                sh 'mv $BUILDSTARTDATE $S3PROJECTDIR/'
                                sh 'cp -pr $S3PROJECTDIR/$BUILDSTARTDATE $S3PROJECTDIR/current'

                                //
                                // put $S3PROJECTDIR/$BUILDSTARTDATE/ and $S3PROJECTDIR/current in s3 bucket
                                //
                                sh '. venv/bin/activate && python3.8 ./go-site/scripts/directory_indexer.py -v --inject ./go-site/scripts/directory-index-template.html --directory $S3PROJECTDIR --prefix https://kg-hub.berkeleybop.io/$S3PROJECTDIR/ -x -u'
                                // for existing builds on s3, we just made an index.html that will clobber the existing (correct) s3 index.html
                                // here we download the existing index.html and clobber the local one instead
                                sh "for dir in `s3cmd ls s3://kg-hub-public-data/kg-covid-19/ | grep '\\/\$' | awk '{print \$NF}' | grep -w -v -E 'raw|current' | xargs -n1 basename`; do s3cmd get --force --continue s3://kg-hub-public-data/kg-covid-19/\$dir/index.html $S3PROJECTDIR/\$dir/ || true; done"

                                sh 's3cmd -c $S3CMD_CFG put -pr --acl-public --cf-invalidate $S3PROJECTDIR s3://kg-hub-public-data/'

                                // Build the top level index.html
                                // "External" packages required to run these scripts.
                                sh '. venv/bin/activate && ./venv/bin/pip install pystache boto3'
                                sh '. venv/bin/activate && python3.8 ./go-site/scripts/bucket-indexer.py --credentials $AWS_JSON --bucket kg-hub-public-data --inject ./go-site/scripts/directory-index-template.html --prefix https://kg-hub.berkeleybop.io/ > top-level-index.html'
                                sh 's3cmd -c $S3CMD_CFG put --acl-public --mime-type=text/html --cf-invalidate top-level-index.html s3://kg-hub-public-data/index.html'

                                // Invalidate the CDN now that the new files are up.
                                sh '. venv/bin/activate && ./venv/bin/pip install awscli'
                                sh 'echo "[preview]" > ./awscli_config.txt && echo "cloudfront=true" >> ./awscli_config.txt'
                                sh '. venv/bin/activate && AWS_CONFIG_FILE=./awscli_config.txt python3.8 ./venv/bin/aws cloudfront create-invalidation --distribution-id $AWS_CLOUDFRONT_DISTRIBUTION_ID --paths "/*"'

                                // Should now appear at:
                                // https://kg-hub.berkeleybop.io/[artifact name]
                            }

                        }
                    }
                }
            }
        }

        stage('Deploy blazegraph') {
            when { anyOf { branch 'master' } }
            steps {

                git([branch: 'master',
                     credentialsId: 'justaddcoffee_github_api_token_username_pw',
                     url: 'https://github.com/geneontology/operations.git'])

                dir('./ansible') {

                    withCredentials([file(credentialsId: 'ansible-bbop-local-slave', variable: 'DEPLOY_LOCAL_IDENTITY')]) {
                        echo 'Push master out to public Blazegraph'
                        retry(3){
                            sh 'ansible-playbook update-kg-hub-endpoint.yaml --inventory=hosts.local-rdf-endpoint --private-key="$DEPLOY_LOCAL_IDENTITY" -e target_user=bbop --extra-vars="endpoint=internal"'
                        }
                    }
                }

            }
        }

    }
}
