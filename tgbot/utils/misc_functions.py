# - *- coding: utf- 8 - *-

import asyncio
import json
from typing import Union

from aiogram import Bot
from aiogram.types import FSInputFile

from tgbot.data.config import get_admins, BOT_VERSION, PATH_DATABASE, get_desc
from tgbot.utils.const_functions import ded
from tgbot.utils.misc.bot_models import ARS



