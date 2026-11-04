"""Every request engine calibrates the same paths in each recursive directory."""
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from lib.core.discovery_config import DiscoveryConfig
from lib.core.execution_config import ExecutionConfig
from lib.core.filter_config import FilterConfig
from lib.core.fuzzer import AsyncFuzzer, Fuzzer, NativeFuzzer
from lib.core.settings import WILDCARD_TEST_POINT_MARKER


class TestScannerSpecs(IsolatedAsyncioTestCase):
    async def test_duplicate_shapes_and_extensions_are_rebuilt_for_each_directory(self):
        marker = WILDCARD_TEST_POINT_MARKER
        for cls in (Fuzzer, AsyncFuzzer, NativeFuzzer):
            with self.subTest(engine=cls.__name__):
                fuzzer = cls(
                    SimpleNamespace(backend=None), None,
                    filter_config=FilterConfig(exclude_response='custom'),
                    discovery_config=DiscoveryConfig(prefixes=('api', 'api', '.'),
                                                     suffixes=('~', '~', '.php'), extensions=('php', 'txt', 'txt')),
                    execution_config=ExecutionConfig(), match_callbacks=(),
                    not_found_callbacks=(), error_callbacks=(),
                )
                target = ('lib.core.fuzzer.AsyncScanner.create' if cls is AsyncFuzzer
                          else 'lib.core.fuzzer.Scanner')
                factory = AsyncMock(return_value=object()) if cls is AsyncFuzzer else None
                with patch(target, **({'new': factory} if factory is not None else {})) as create:
                    for directory in ('first/', 'second/'):
                        create.reset_mock()
                        fuzzer.set_base_path(directory)
                        if cls is AsyncFuzzer:
                            await fuzzer.setup_scanners()
                        else:
                            fuzzer.setup_scanners()
                        self.assertEqual([call.kwargs['path'] for call in create.call_args_list], [
                            directory + marker, 'custom', directory + 'api' + marker,
                            directory + '.' + marker, directory + '.ht' + marker,
                            directory + marker + '~', directory + marker + '.php',
                            directory + marker + '/', directory + marker + '.txt',
                        ])
                        self.assertIsNone(create.call_args_list[0].kwargs['tested'])
