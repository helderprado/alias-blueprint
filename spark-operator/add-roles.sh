kubectl create serviceaccount spark --namespace=spark-operator
kubectl create clusterrolebinding spark-role --clusterrole=edit --serviceaccount=spark-operator:spark --namespace=spark-operator
