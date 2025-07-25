import os
import zipfile
from unittest.mock import *

import platformdirs
from downloads import LDRAW_URL

from ldraw import download


@patch("os.path.exists", side_effect=lambda s: False)
@patch("zipfile.ZipFile", spec=zipfile.ZipFile)
@patch("ldraw.downloads._download_progress")
@patch("ldraw.downloads.generate_parts_lst")
def test_download(
    generate_parts_lst_mock,
    download_progress_mock,
    zip_mock,
    os_path_exists_mock,
    tmp_path,
):
    download()

    download_progress_mock.assert_called_once()
    generate_parts_lst_mock.assert_called_once()
