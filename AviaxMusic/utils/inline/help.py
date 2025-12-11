from typing import Union

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from AviaxMusic import app
from AviaxMusic.utils.database import get_lang


def help_pannel(_, START: Union[bool, int] = None, page: int = 1):
    first = [InlineKeyboardButton(text=_["CLOSE_BUTTON"], callback_data=f"close")]
    second = [
        InlineKeyboardButton(
            text=_["BACK_BUTTON"],
            callback_data=f"settingsback_helper",
        ),
    ]
    mark = second if START else first
    
    if page == 1:
        upl = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=_["H_B_1"],
                        callback_data="help_callback hb1",
                    ),
                    InlineKeyboardButton(
                        text=_["H_B_2"],
                        callback_data="help_callback hb2",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=_["H_B_3"],
                        callback_data="help_callback hb3",
                    ),
                    InlineKeyboardButton(
                        text=_["H_B_4"],
                        callback_data="help_callback hb4",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=_["H_B_5"],
                        callback_data="help_callback hb5",
                    ),
                    InlineKeyboardButton(
                        text=_["H_B_6"],
                        callback_data="help_callback hb6",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Next",
                        callback_data="help_page 2",
                    ),
                ],
                mark,
            ]
        )
    
    elif page == 2:
        upl = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=_["H_B_7"],
                        callback_data="help_callback hb7",
                    ),
                    InlineKeyboardButton(
                        text=_["H_B_8"],
                        callback_data="help_callback hb8",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=_["H_B_9"],
                        callback_data="help_callback hb9",
                    ),
                    InlineKeyboardButton(
                        text=_["H_B_10"],
                        callback_data="help_callback hb10",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=_["H_B_11"],
                        callback_data="help_callback hb11",
                    ),
                    InlineKeyboardButton(
                        text=_["H_B_12"],
                        callback_data="help_callback hb12",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Back",
                        callback_data="help_page 1",
                    ),
                    InlineKeyboardButton(
                        text="Next",
                        callback_data="help_page 3",
                    ),
                ],
                mark,
            ]
        )
    
    elif page == 3:
        upl = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=_["H_B_13"],
                        callback_data="help_callback hb13",
                    ),
                    InlineKeyboardButton(
                        text=_["H_B_14"],
                        callback_data="help_callback hb14",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=_["H_B_15"],
                        callback_data="help_callback hb15",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Back",
                        callback_data="help_page 2",
                    ),
                ],
                mark,
            ]
        )
    
    return upl


def help_back_markup(_):
    upl = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=_["BACK_BUTTON"],
                    callback_data=f"settings_back_helper",
                ),
            ]
        ]
    )
    return upl


def private_help_panel(_):
    buttons = [
        [
            InlineKeyboardButton(
                text=_["S_B_4"],
                url=f"https://t.me/{app.username}?start=help",
            ),
        ],
    ]
    return buttons


@app.on_callback_query(filters.regex("help_page"))
async def help_page_callback(client, callback_query: CallbackQuery):
    try:
        from strings import get_string
        
        language = await get_lang(callback_query.from_user.id)
        _ = get_string(language)
        
        page = int(callback_query.data.split()[1])
        
        keyboard = help_pannel(_, START=True, page=page)
        
        await callback_query.edit_message_reply_markup(
            reply_markup=keyboard
        )
        await callback_query.answer()
        
    except Exception as e:
        await callback_query.answer(f"Error: {e}", show_alert=True)