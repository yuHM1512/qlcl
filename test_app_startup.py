"""Verify both application and included-router lifespan startup hooks."""
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from flat_output import DDL, register


class StartupTests(unittest.TestCase):
    def test_lifespan_runs_sync_and_flat_output_initialization(self):
        connect = MagicMock()
        app = FastAPI(lifespan=main.lifespan)
        register(app, connect, 'test-key')
        with patch.object(main, 'start_qtcn_auto_sync_if_enabled') as qtcn, \
             patch.object(main, 'start_xnv2_auto_sync_if_enabled') as xnv2, \
             patch.object(main, 'start_flat_line_auto_sync_if_enabled') as flat:
            with TestClient(app):
                qtcn.assert_called_once_with()
                xnv2.assert_called_once_with()
                flat.assert_called_once_with()
                connection = connect.return_value.__enter__.return_value
                connection.cursor.return_value.__enter__.return_value.execute.assert_called_once_with(DDL)
                connection.commit.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
