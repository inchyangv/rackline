# HashCredit Makefile
# Common commands for development

.PHONY: build test clean fmt lint deploy relayer

# Load environment variables from .env (if present).
# Note: Keep `.env` in simple KEY=VALUE format (no `export` statements).
ifneq (,$(wildcard .env))
include .env
export
endif

# ============================================
# Solidity (Foundry)
# ============================================

build:
	forge build

test:
	forge test -vvv

test-gas:
	forge test -vvv --gas-report

clean:
	forge clean

fmt:
	forge fmt

fmt-check:
	forge fmt --check

snapshot:
	forge snapshot

# ============================================
# Deployment
# ============================================

deploy-local:
	forge script script/Deploy.s.sol --rpc-url http://localhost:8545 --broadcast

deploy-testnet:
	forge script script/Deploy.s.sol --rpc-url $(RPC_URL) --broadcast

deploy-testnet-verify:
	forge script script/Deploy.s.sol --rpc-url $(RPC_URL) --broadcast --verify

# ============================================
# Python Relayer
# ============================================

relayer-install:
	cd offchain/relayer && pip install -e .

relayer-run:
	python -m hashcredit_relayer

relayer-test:
	cd offchain/relayer && pytest

# ============================================
# Live SPV Demo
# ============================================

demo-live-spv:
	bash script/demo_live_spv.sh

# ============================================
# Development Helpers
# ============================================

anvil:
	anvil --chain-id 31337

help:
	@echo "HashCredit Development Commands:"
	@echo "  make build          - Build Solidity contracts"
	@echo "  make test           - Run Foundry tests"
	@echo "  make test-gas       - Run tests with gas report"
	@echo "  make clean          - Clean build artifacts"
	@echo "  make fmt            - Format Solidity code"
	@echo "  make deploy-local   - Deploy to local Anvil"
	@echo "  make deploy-testnet - Deploy to testnet"
	@echo "  make relayer-install- Install Python relayer"
	@echo "  make relayer-run    - Run the relayer"
	@echo "  make anvil          - Start local Anvil node"
	@echo "  make demo-live-spv  - One-click SPV live demo pipeline"
