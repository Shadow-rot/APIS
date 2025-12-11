from pyrogram.types import InlineKeyboardButton

import config
from AviaxMusic import app


def start_panel(_):
    buttons = [
        [
            InlineKeyboardButton(
                text=f"✨ {_['S_B_1']}", 
                url=f"https://t.me/{app.username}?startgroup=true"
            ),
            InlineKeyboardButton(
                text=f"💬 {_['S_B_2']}", 
                url=config.SUPPORT_GROUP
            ),
        ],
    ]
    return buttons


def private_panel(_):
    buttons = [
        [
            InlineKeyboardButton(
                text=f"➕ {_['S_B_3']}",
                url=f"https://t.me/{app.username}?startgroup=true",
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"❓ {_['S_B_4']}", 
                callback_data="settings_back_helper"
            ),
            InlineKeyboardButton(
                text=f"👨‍💻 {_['S_B_5']}", 
                user_id=config.OWNER_ID
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"💭 {_['S_B_2']}", 
                url=config.SUPPORT_GROUP
            ),
            InlineKeyboardButton(
                text=f"📣 {_['S_B_6']}", 
                url=config.SUPPORT_CHANNEL
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"🔗 {_['S_B_7']}", 
                url=config.UPSTREAM_REPO
            ),
        ],
    ]
    return buttons