# Objective
It is a simple service to practice arithmetic progression concepts. It is necessary to install flask as part of this solution in order to creqte service qnd run as a local server.

# Installing Flask
https://flask.palletsprojects.com/en/1.1.x/installation/

# Running application in Power Shell Terminal

$env:FLASK_APP = "ap.py"

python -m flask run

Example: http://127.0.0.1:5000/sumProgression/2/2/2

# Deploy Bitbucket + Heroku en une commande

## Origine du trafic dans le dashboard

Le dashboard admin (`/admin/usage-dashboard`) affiche les requêtes API par origine : site web, application mobile ou non identifiée. Les mêmes filtres de ville, ligne et dates s'appliquent à cette répartition.

Pour identifier les clients de façon fiable, envoyez `X-Client-Application: web` depuis le site et `X-Client-Application: mobile` depuis l'application. Pour les requêtes historiques sans cet en-tête, le serveur utilise le `User-Agent` lorsqu'il est reconnaissable. Un navigateur sur téléphone reste classé comme site web. Les autres requêtes restent non identifiées.

## Chaves individuais da API

Abra `https://mybusaoservice.audeladedonnees.fr/developer`, selecione um dos seis idiomas (português, inglês, francês, espanhol, italiano ou alemão), crie uma conta de desenvolvedor (senha com pelo menos 12 caracteres), entre e escolha **Gerar chave**. Copie a chave no momento da criação: o servidor guarda apenas seu hash e não pode mostrá-la novamente. Você pode manter até três chaves ativas e revogá-las na mesma página.

### GTFS Realtime por cidade

O painel administrativo consulta `/admin/gtfs-realtime/status` para mostrar disponibilidade e idade dos fluxos GTFS Realtime. Configure no servidor a variável `GTFS_REALTIME_FEEDS` com um objeto JSON cujas chaves são os mesmos IDs de cidade usados nas rotas da API:

```json
{
  "Grenoble_France": {
    "tripUpdates": {"url": "https://provider.example/trips.pb", "headers": {"X-API-Key": "secret"}},
    "vehiclePositions": "https://provider.example/vehicles.pb",
    "serviceAlerts": "https://provider.example/alerts.pb"
  }
}
```

Cada tipo de fluxo é opcional. As URLs precisam usar HTTPS; mantenha chaves em `headers` da configuração do servidor, nunca no JavaScript do painel. O endpoint exige token de administrador, aceita `?city=Grenoble_France` e omite URLs e credenciais da resposta. As cidades do GTFS estático sem feed configurado aparecem como **Não configurado**. As verificações têm timeout de 5 segundos, limite de 5 MB e cache de 30 segundos. O estado **Antigo** usa o timestamp do cabeçalho: mais de 90 segundos para viagens/veículos ou 10 minutos para alertas. É uma checagem de saúde do feed; não valida cada entidade nem comprova cobertura completa da cidade.

Envie a chave em `X-API-Key` (ou no cabeçalho legado `token`) para consultas de transporte:

```bash
curl -H 'X-API-Key: SUA_CHAVE' \
  https://mybusaoservice.audeladedonnees.fr/getRoutes/Grenoble_France
```

As chaves são limitadas a 120 consultas por minuto e não autorizam rotas administrativas, logs nem escrita. Não inclua a chave em URLs, repositórios ou JavaScript público. Para servidores próprios, guarde-a numa variável de ambiente. O site Meu Busão também aceita `MEUBUSAO_API_KEY` no servidor em vez do antigo `MEUBUSAO_API_TOKEN` (identificador compartilhado). O dashboard administrativo continua usando login e senha separados.

Un script est disponible: [deploy.sh](deploy.sh)

## Pré-requis

- Avoir les remotes Git configurés:
	- `origin` (Bitbucket)
	- `heroku` (Heroku), ex: `heroku git:remote -a <nom-app>`

## Utilisation

1. Donner les droits d'exécution (une seule fois):

```bash
chmod +x deploy.sh
```

2. Déployer la branche courante vers Bitbucket + Heroku:

```bash
./deploy.sh
```

3. Déployer une branche spécifique:

```bash
./deploy.sh main
```

## Variables optionnelles

- `BITBUCKET_REMOTE` (défaut: `origin`)
- `HEROKU_REMOTE` (défaut: `heroku`)
- `HEROKU_BRANCH` (défaut: `main`)

Exemple:

```bash
HEROKU_BRANCH=master ./deploy.sh
```
