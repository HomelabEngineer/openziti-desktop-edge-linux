.PHONY: all deb rpm test run-mock clean

all: deb rpm

deb:
	packaging/build.sh deb

rpm:
	packaging/build.sh rpm

test:
	python3 -m unittest discover -s tests -v

# GUI against the mock tunneler (see tests/mock_tunnel.py)
run-mock:
	@mkdir -p .mock; python3 tests/mock_tunnel.py --dir .mock serve & \
	sleep 1; ZDE_SOCKET_DIR=$(CURDIR)/.mock/sock ZDE_SKIP_GROUP_CHECK=1 \
	ZDE_MOCK_SYSTEMD="python3 $(CURDIR)/tests/mock_tunnel.py --dir $(CURDIR)/.mock systemctl" \
	ZDE_JOURNAL_CMD="python3 $(CURDIR)/tests/mock_tunnel.py --dir $(CURDIR)/.mock journal" \
	PYTHONPATH=src python3 -m ziti_desktop_edge --debug; kill %1 2>/dev/null || true

clean:
	rm -rf dist .mock build
	find . -name __pycache__ -prune -exec rm -rf {} +
