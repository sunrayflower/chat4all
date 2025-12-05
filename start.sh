#!/bin/bash

# ============================================================================
# Chat4All v2 - Quick Start Script
# Inicia todos os serviços necessários
# ============================================================================

set -e  # Exit on error

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       Chat4All v2 - Sistema de Comunicação Ubíqua            ║"
echo "║         Tecnologias: gRPC + Kafka + WebSockets              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# STEP 1: Verificar pré-requisitos
# ============================================================================

echo "[1/6] Verificando pré-requisitos..."

if ! command -v docker &> /dev/null; then
    echo "❌ Docker não está instalado"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose não está instalado"
    exit 1
fi

echo "✓ Docker instalado: $(docker --version)"
echo "✓ Docker Compose instalado: $(docker-compose --version)"

# ============================================================================
# STEP 2: Preparar ambiente
# ============================================================================

echo ""
echo "[2/6] Preparando ambiente..."

if [ ! -f .env ]; then
    echo "  → Criando .env a partir de .env.example"
    cp env.example .env
else
    echo "  → .env já existe"
fi

echo "✓ Ambiente configurado"

# ============================================================================
# STEP 3: Build das imagens
# ============================================================================

echo ""
echo "[3/6] Construindo imagens Docker..."
echo "  (Isto pode levar 2-3 minutos na primeira vez)"

docker-compose build --quiet

echo "✓ Imagens construídas com sucesso"

# ============================================================================
# STEP 4: Iniciar containers
# ============================================================================

echo ""
echo "[4/6] Iniciando containers..."

docker-compose up -d

echo "✓ Containers iniciados"

# ============================================================================
# STEP 5: Aguardar inicialização
# ============================================================================

echo ""
echo "[5/6] Aguardando inicialização dos serviços..."
echo "  (Isto pode levar 20-30 segundos)"

# Aguardar MongoDB
echo -n "  → MongoDB: "
for i in {1..30}; do
    if docker-compose exec -T mongodb mongosh -u admin -p password --eval "db.adminCommand('ping')" &> /dev/null; then
        echo "✓"
        break
    fi
    echo -n "."
    sleep 1
done

# Aguardar Kafka
echo -n "  → Kafka: "
for i in {1..30}; do
    if docker-compose exec -T kafka kafka-broker-api-versions --bootstrap-server kafka:29092 &> /dev/null; then
        echo "✓"
        break
    fi
    echo -n "."
    sleep 1
done

# Aguardar Backend
echo -n "  → Backend (gRPC/WebSocket): "
for i in {1..30}; do
    if docker-compose exec -T chat4all-backend curl -s http://localhost:8000/health &> /dev/null; then
        echo "✓"
        break
    fi
    echo -n "."
    sleep 1
done

echo "✓ Todos os serviços estão saudáveis"

# ============================================================================
# STEP 6: Mostrar informações de acesso
# ============================================================================

echo ""
echo "[6/6] Serviços iniciados com sucesso!"
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                   SERVIÇOS DISPONÍVEIS                       ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                                                              ║"
echo "║  📡 gRPC Server                                              ║"
echo "║     → localhost:50051                                        ║"
echo "║                                                              ║"
echo "║  🔌 WebSocket Server                                         ║"
echo "║     → ws://localhost:8765                                    ║"
echo "║                                                              ║"
echo "║  🗄️  MongoDB                                                  ║"
echo "║     → mongodb://admin:password@localhost:27017               ║"
echo "║                                                              ║"
echo "║  🚀 Kafka Broker                                             ║"
echo "║     → localhost:9092                                         ║"
echo "║                                                              ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                   DASHBOARDS & INTERFACES                    ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                                                              ║"
echo "║  📊 Grafana (Dashboards)                                     ║"
echo "║     → http://localhost:3000                                  ║"
echo "║     → Usuário: admin / Senha: admin                          ║"
echo "║                                                              ║"
echo "║  📈 Prometheus (Métricas)                                    ║"
echo "║     → http://localhost:9090                                  ║"
echo "║                                                              ║"
echo "║  🚀 Kafka UI                                                 ║"
echo "║     → http://localhost:8080                                  ║"
echo "║                                                              ║"
echo "║  🍃 Mongo Express (MongoDB UI)                               ║"
echo "║     → http://localhost:8081                                  ║"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# Comandos úteis
# ============================================================================

echo "🔧 COMANDOS ÚTEIS:"
echo ""
echo "  Ver logs em tempo real:"
echo "    docker-compose logs -f chat4all-backend"
echo ""
echo "  Executar testes:"
echo "    python3 test_chat4all.py"
echo ""
echo "  Parar serviços:"
echo "    docker-compose stop"
echo ""
echo "  Parar e remover tudo:"
echo "    docker-compose down -v"
echo ""
echo "  Acessar Kafka CLI:"
echo "    docker-compose exec kafka bash"
echo ""
echo "  Acessar MongoDB:"
echo "    docker-compose exec mongodb mongosh -u admin -p password"
echo ""

# ============================================================================
# Status final
# ============================================================================

echo ""
docker-compose ps

echo ""
echo "✅ Chat4All v2 está pronto para uso!"
echo ""
echo "Próximos passos:"
echo "  1. Abra http://localhost:3000 (Grafana) para monitoramento"
echo "  2. Execute 'python3 test_chat4all.py' para testes"
echo "  3. Consulte README.md para mais informações"
echo ""
