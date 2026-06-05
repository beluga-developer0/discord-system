import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import sys
from datetime import datetime, timedelta, timezone
import re
from typing import Optional
import asyncio

# ═══════════════ НАСТРОЙКИ ═══════════════
intents = discord.Intents.default()
intents.message_content = True

DATA_FILE = 'blacklist_data.json'
CONFIG_FILE = 'bot_config.json'
SETTINGS_FILE = 'bot_settings.json'
TOKEN_FILE = 'token.json'

EMOJIS = {
    'success': '✅', 'error': '❌', 'warning': '⚠️', 'info': 'ℹ️',
    'ban': '🚫', 'appeal': '📝', 'list': '📋', 'search': '🔍',
    'stats': '📊', 'crown': '👑', 'shield': '🛡️', 'clock': '🕐',
    'permanent': '♾️', 'active': '🟢', 'pending': '🟡', 'new': '🆕'
}

# ═══════════════ ФУНКЦИИ ДАННЫХ ═══════════════
def load_json(filename, default=None):
    if default is None:
        default = {}
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def save_token(token):
    save_json(TOKEN_FILE, {'token': token, 'saved_at': datetime.now(timezone.utc).isoformat()})

def load_token():
    data = load_json(TOKEN_FILE)
    return data.get('token') if data else None

# ═══════════════ СИСТЕМА ЧС ═══════════════
class BlacklistSystem:
    def __init__(self):
        self.data = load_json(DATA_FILE, {
            'blacklists': [], 'appeals': [], 'history': [],
            'statistics': {'total_issued': 0, 'total_removed': 0, 
                          'total_appeals': 0, 'accepted_appeals': 0, 'rejected_appeals': 0}
        })
        self.config = load_json(CONFIG_FILE, {
            'beluga_id': None, 'moderators': [], 'auto_unban': True
        })
        self.settings = load_json(SETTINGS_FILE, {
            'dm_notifications': True, 'log_channel': None, 'appeal_cooldown': 3600
        })
        self.check_expired()
    
    def set_beluga_id(self, user_id):
        self.config['beluga_id'] = str(user_id)
        save_json(CONFIG_FILE, self.config)
    
    def get_beluga_id(self):
        return self.config.get('beluga_id')
    
    def is_beluga(self, user_id):
        return str(user_id) == self.get_beluga_id()
    
    def is_moderator(self, user_id):
        return str(user_id) in self.config.get('moderators', []) or self.is_beluga(user_id)
    
    def add_moderator(self, user_id):
        if str(user_id) not in self.config.get('moderators', []):
            self.config.setdefault('moderators', []).append(str(user_id))
            save_json(CONFIG_FILE, self.config)
            return True
        return False
    
    def remove_moderator(self, user_id):
        if str(user_id) in self.config.get('moderators', []):
            self.config['moderators'].remove(str(user_id))
            save_json(CONFIG_FILE, self.config)
            return True
        return False
    
    def check_expired(self):
        now = datetime.now(timezone.utc)
        changed = False
        
        for bl in self.data['blacklists']:
            if bl.get('active', True) and bl.get('expires_at') != 'permanent':
                try:
                    expires = datetime.fromisoformat(bl['expires_at'])
                    if now > expires:
                        bl['active'] = False
                        bl['auto_removed'] = True
                        bl['removed_at'] = now.isoformat()
                        changed = True
                        self.data['statistics']['total_removed'] += 1
                        self.data['history'].append({
                            'type': 'auto_remove', 'target_id': bl['target_id'],
                            'timestamp': now.isoformat(), 'reason': 'Срок истек'
                        })
                except:
                    pass
        
        if changed:
            save_json(DATA_FILE, self.data)
        return changed
    
    def calculate_expiry(self, duration_str):
        if duration_str.lower() in ['permanent', 'навсегда', 'perm']:
            return 'permanent'
        
        total_seconds = 0
        patterns = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800, 'mo': 2592000}
        matches = re.findall(r'(\d+)\s*(mo|w|d|h|m|s)', duration_str.lower())
        for value, unit in matches:
            total_seconds += int(value) * patterns.get(unit, 0)
        
        if total_seconds > 0:
            return (datetime.now(timezone.utc) + timedelta(seconds=total_seconds)).isoformat()
        return 'permanent'
    
    def format_timestamp(self, iso_time):
        if iso_time == 'permanent':
            return "♾️ Навсегда"
        try:
            dt = datetime.fromisoformat(iso_time)
            timestamp = int(dt.timestamp())
            return f"<t:{timestamp}:F> (<t:{timestamp}:R>)"
        except:
            return iso_time
    
    def get_blacklist(self, target_id):
        self.check_expired()
        for bl in self.data['blacklists']:
            if bl['target_id'] == str(target_id) and bl.get('active', True):
                return bl
        return None
    
    def add_blacklist(self, target_id, reason, duration_str, issued_by):
        self.remove_blacklist(target_id, str(issued_by))
        
        entry = {
            'target_id': str(target_id), 'reason': reason, 'duration': duration_str,
            'issued_by': str(issued_by), 'issued_at': datetime.now(timezone.utc).isoformat(),
            'expires_at': self.calculate_expiry(duration_str), 'active': True
        }
        self.data['blacklists'].append(entry)
        self.data['statistics']['total_issued'] += 1
        self.data['history'].append({
            'type': 'blacklist', 'target_id': str(target_id), 'issued_by': str(issued_by),
            'reason': reason, 'duration': duration_str, 'timestamp': datetime.now(timezone.utc).isoformat()
        })
        save_json(DATA_FILE, self.data)
        return entry
    
    def remove_blacklist(self, target_id, removed_by='system'):
        removed = False
        for bl in self.data['blacklists']:
            if bl['target_id'] == str(target_id) and bl.get('active', True):
                bl['active'] = False
                bl['removed_at'] = datetime.now(timezone.utc).isoformat()
                bl['removed_by'] = removed_by
                removed = True
                self.data['statistics']['total_removed'] += 1
        if removed:
            save_json(DATA_FILE, self.data)
        return removed
    
    def all_active(self):
        self.check_expired()
        return [bl for bl in self.data['blacklists'] if bl.get('active', True)]
    
    def add_appeal(self, target_id, text, evidence=None):
        recent = [a for a in self.data['appeals'] 
                 if a['target_id'] == str(target_id) and 
                 (datetime.now(timezone.utc) - datetime.fromisoformat(a['timestamp'])).seconds < self.settings.get('appeal_cooldown', 3600)]
        if recent:
            return None, "cooldown"
        
        appeal = {
            'appeal_id': len(self.data['appeals']) + 1, 'target_id': str(target_id),
            'text': text, 'evidence': evidence, 'timestamp': datetime.now(timezone.utc).isoformat(),
            'status': 'pending', 'reviewed_by': None, 'reviewed_at': None, 'review_comment': None
        }
        self.data['appeals'].append(appeal)
        self.data['statistics']['total_appeals'] += 1
        save_json(DATA_FILE, self.data)
        return appeal, 'success'
    
    def review_appeal(self, appeal_id, status, reviewer_id, comment=None):
        for appeal in self.data['appeals']:
            if appeal['appeal_id'] == appeal_id:
                appeal['status'] = status
                appeal['reviewed_by'] = str(reviewer_id)
                appeal['reviewed_at'] = datetime.now(timezone.utc).isoformat()
                appeal['review_comment'] = comment
                if status == 'approved':
                    self.data['statistics']['accepted_appeals'] += 1
                    self.remove_blacklist(appeal['target_id'], f'appeal_{appeal_id}')
                else:
                    self.data['statistics']['rejected_appeals'] += 1
                save_json(DATA_FILE, self.data)
                return True
        return False
    
    def get_pending_appeals(self):
        return [a for a in self.data['appeals'] if a['status'] == 'pending']
    
    def get_statistics(self):
        return self.data['statistics']

# ═══════════════ ДЕКОРАТОРЫ ═══════════════
def check_beluga():
    async def predicate(interaction: discord.Interaction):
        if not interaction.client.bl_system:
            await interaction.response.send_message("⚠️ Система ЧС не инициализирована!", ephemeral=True)
            return False
        if interaction.client.bl_system.is_beluga(interaction.user.id):
            return True
        await interaction.response.send_message(
            embed=discord.Embed(title=f"{EMOJIS['error']} Доступ запрещен", 
                               description="Только для **Beluga Develop**!", color=0xFF0000),
            ephemeral=True
        )
        return False
    return app_commands.check(predicate)

def check_staff():
    async def predicate(interaction: discord.Interaction):
        if not interaction.client.bl_system:
            await interaction.response.send_message("⚠️ Система ЧС не инициализирована!", ephemeral=True)
            return False
        if interaction.client.bl_system.is_moderator(interaction.user.id):
            return True
        await interaction.response.send_message(
            embed=discord.Embed(title=f"{EMOJIS['error']} Доступ запрещен", 
                               description="Только для **модераторов**!", color=0xFF0000),
            ephemeral=True
        )
        return False
    return app_commands.check(predicate)

# ═══════════════ ФУНКЦИЯ УВЕДОМЛЕНИЯ ═══════════════
async def send_appeal_notification(bot_instance, appeal):
    bl_system = bot_instance.bl_system
    embed = discord.Embed(title=f"{EMOJIS['new']} НОВОЕ ОБЖАЛОВАНИЕ #{appeal['appeal_id']}",
                          color=0xFFA500, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="👤 ID пользователя", value=f"`{appeal['target_id']}`", inline=True)
    embed.add_field(name="📝 Текст", value=appeal['text'][:500], inline=False)
    if appeal.get('evidence'):
        embed.add_field(name="🔗 Доказательства", value=appeal['evidence'], inline=False)
    
    beluga_id = bl_system.get_beluga_id()
    if beluga_id:
        try:
            user = await bot_instance.fetch_user(int(beluga_id))
            await user.send(embed=embed)
        except:
            pass
    
    for mod_id in bl_system.config.get('moderators', []):
        try:
            user = await bot_instance.fetch_user(int(mod_id))
            await user.send(embed=embed)
        except:
            pass

# ═══════════════ ПАГИНАЦИЯ ═══════════════
class BlacklistPaginator(discord.ui.View):
    def __init__(self, entries, bl_system, bot_instance):
        super().__init__(timeout=120)
        self.entries = entries
        self.bl_system = bl_system
        self.bot_instance = bot_instance
        self.page = 0
        self.per_page = 10
    
    def get_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page
        current = self.entries[start:end]
        total_pages = (len(self.entries) + self.per_page - 1) // self.per_page
        
        embed = discord.Embed(title=f"📋 АКТИВНЫЕ ЧС ({len(self.entries)})", color=0xFF0000)
        
        for i, entry in enumerate(current, start + 1):
            user = self.bot_instance.get_user(int(entry['target_id']))
            name = user.name if user else f"ID: {entry['target_id']}"
            time_str = self.bl_system.format_timestamp(entry['expires_at'])
            embed.add_field(
                name=f"#{i} {name}",
                value=f"📝 {entry['reason']}\n⏰ {time_str}",
                inline=False
            )
        
        embed.set_footer(text=f"Страница {self.page + 1}/{total_pages}")
        return embed
    
    @discord.ui.button(label="◀ Назад", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
    
    @discord.ui.button(label="Вперед ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (self.page + 1) * self.per_page < len(self.entries):
            self.page += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
    
    @discord.ui.button(label="🔄 Обновить", style=discord.ButtonStyle.primary)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

class AppealPaginator(discord.ui.View):
    def __init__(self, appeals):
        super().__init__(timeout=120)
        self.appeals = appeals
        self.page = 0
        self.per_page = 5
    
    def get_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page
        current = self.appeals[start:end]
        total_pages = (len(self.appeals) + self.per_page - 1) // self.per_page
        
        embed = discord.Embed(title=f"📝 Ожидающие обжалования ({len(self.appeals)})", color=0xFFA500)
        for appeal in current:
            embed.add_field(
                name=f"#{appeal['appeal_id']} | ID: {appeal['target_id']}",
                value=f"📝 {appeal['text'][:100]}...",
                inline=False
            )
        embed.set_footer(text=f"Страница {self.page + 1}/{total_pages}")
        return embed
    
    @discord.ui.button(label="◀ Назад", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
    
    @discord.ui.button(label="Вперед ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (self.page + 1) * self.per_page < len(self.appeals):
            self.page += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

# ═══════════════ ГРУППЫ КОМАНД ═══════════════
class BlacklistCommands(app_commands.Group):
    def __init__(self):
        super().__init__(name='чс', description='Управление черным списком')
    
    @app_commands.command(name='выдать', description='Выдать ЧС пользователю')
    @app_commands.describe(пользователь='Кому выдать ЧС', время='Срок (1d, 12h, 30m, 1w, permanent)', причина='Причина выдачи ЧС')
    @check_beluga()
    async def give_blacklist(self, interaction: discord.Interaction, пользователь: discord.User, время: str, причина: str):
        bl = interaction.client.bl_system
        
        if пользователь.id == interaction.user.id:
            await interaction.response.send_message("❌ Нельзя выдать ЧС самому себе!", ephemeral=True)
            return
        if пользователь.bot:
            await interaction.response.send_message("❌ Нельзя выдать ЧС ботам!", ephemeral=True)
            return
        if bl.get_blacklist(пользователь.id):
            await interaction.response.send_message(f"⚠️ {пользователь.mention} уже в ЧС!", ephemeral=True)
            return
        
        bl.add_blacklist(пользователь.id, причина, время, interaction.user.id)
        
        embed = discord.Embed(title=f"{EMOJIS['success']} ЧС ВЫДАН!", color=0x00FF00)
        embed.add_field(name="👤 Пользователь", value=f"{пользователь.name} (`{пользователь.id}`)", inline=True)
        embed.add_field(name="⏰ Срок", value=f"`{время}`", inline=True)
        embed.add_field(name="📝 Причина", value=f"```{причина}```", inline=False)
        embed.add_field(name="🗓️ Истекает", value=bl.format_timestamp(bl.calculate_expiry(время)), inline=False)
        
        await interaction.response.send_message(embed=embed)
        
        try:
            await пользователь.send(f"🚫 **Вам выдан ЧС!**\n📝 Причина: {причина}\n⏰ Срок: {время}")
        except:
            pass
    
    @app_commands.command(name='снять', description='Снять ЧС с пользователя')
    @app_commands.describe(пользователь='С кого снять ЧС')
    @check_beluga()
    async def remove_blacklist(self, interaction: discord.Interaction, пользователь: discord.User):
        bl = interaction.client.bl_system
        
        if not bl.get_blacklist(пользователь.id):
            await interaction.response.send_message(f"⚠️ {пользователь.name} не в ЧС!", ephemeral=True)
            return
        
        bl.remove_blacklist(пользователь.id, str(interaction.user.id))
        await interaction.response.send_message(f"{EMOJIS['success']} ЧС снят с {пользователь.mention}")
        
        try:
            await пользователь.send(f"✅ **ЧС снят!** С вас снят черный список.")
        except:
            pass
    
    @app_commands.command(name='список', description='Список всех ЧС')
    @check_beluga()
    async def list_blacklist(self, interaction: discord.Interaction):
        bl = interaction.client.bl_system
        active = bl.all_active()
        
        if not active:
            await interaction.response.send_message("📋 Нет активных ЧС")
            return
        
        view = BlacklistPaginator(active, bl, interaction.client)
        await interaction.response.send_message(embed=view.get_embed(), view=view)
    
    @app_commands.command(name='инфо', description='Информация о ЧС пользователя')
    @app_commands.describe(пользователь='Пользователь')
    @check_staff()
    async def check_user(self, interaction: discord.Interaction, пользователь: discord.User):
        bl = interaction.client.bl_system
        blacklist = bl.get_blacklist(пользователь.id)
        
        embed = discord.Embed(title=f"🔍 Информация о {пользователь.name}", color=0x3498db)
        
        if blacklist:
            embed.add_field(name="Статус", value="🔴 В ЧС", inline=True)
            embed.add_field(name="Причина", value=blacklist['reason'], inline=True)
            embed.add_field(name="Срок", value=blacklist['duration'], inline=True)
            embed.add_field(name="Истекает", value=bl.format_timestamp(blacklist['expires_at']), inline=False)
        else:
            embed.add_field(name="Статус", value="🟢 Чист", inline=True)
        
        await interaction.response.send_message(embed=embed)

class ModeratorCommands(app_commands.Group):
    def __init__(self):
        super().__init__(name='модер', description='Управление модераторами')
    
    @app_commands.command(name='добавить', description='Добавить модератора')
    @app_commands.describe(пользователь='Новый модератор')
    @check_beluga()
    async def add_mod(self, interaction: discord.Interaction, пользователь: discord.User):
        if interaction.client.bl_system.add_moderator(пользователь.id):
            await interaction.response.send_message(f"✅ {пользователь.mention} теперь модератор")
        else:
            await interaction.response.send_message("⚠️ Уже модератор")
    
    @app_commands.command(name='удалить', description='Удалить модератора')
    @app_commands.describe(пользователь='Модератор')
    @check_beluga()
    async def remove_mod(self, interaction: discord.Interaction, пользователь: discord.User):
        if interaction.client.bl_system.remove_moderator(пользователь.id):
            await interaction.response.send_message(f"✅ {пользователь.mention} больше не модератор")
        else:
            await interaction.response.send_message("❌ Не модератор")

class AppealCommands(app_commands.Group):
    def __init__(self):
        super().__init__(name='обжаловать', description='Обжалование ЧС')
    
    @app_commands.command(name='список', description='Список обжалований')
    @check_staff()
    async def appeal_list(self, interaction: discord.Interaction):
        bl = interaction.client.bl_system
        pending = bl.get_pending_appeals()
        
        if not pending:
            await interaction.response.send_message("✅ Нет обжалований")
            return
        
        view = AppealPaginator(pending)
        await interaction.response.send_message(embed=view.get_embed(), view=view)
    
    @app_commands.command(name='рассмотреть', description='Рассмотреть обжалование')
    @app_commands.describe(номер='Номер заявки', решение='Одобрить или отклонить', комментарий='Комментарий')
    @app_commands.choices(решение=[
        app_commands.Choice(name='Одобрить', value='approved'),
        app_commands.Choice(name='Отклонить', value='rejected')
    ])
    @check_staff()
    async def review_appeal(self, interaction: discord.Interaction, номер: int, решение: str, комментарий: Optional[str] = None):
        bl = interaction.client.bl_system
        
        target_appeal = None
        for appeal in bl.data['appeals']:
            if appeal['appeal_id'] == номер:
                target_appeal = appeal
                break
        
        if bl.review_appeal(номер, решение, interaction.user.id, комментарий):
            status_text = "одобрено" if решение == 'approved' else "отклонено"
            await interaction.response.send_message(f"✅ Обжалование #{номер} {status_text}")
            
            if target_appeal:
                try:
                    user = await interaction.client.fetch_user(int(target_appeal['target_id']))
                    result_embed = discord.Embed(
                        title=f"📝 Решение по обжалованию #{номер}",
                        description="✅ **Одобрено!** ЧС снят." if решение == 'approved' else "❌ **Отклонено**",
                        color=0x00FF00 if решение == 'approved' else 0xFF0000
                    )
                    if комментарий:
                        result_embed.add_field(name="Комментарий модератора", value=комментарий, inline=False)
                    await user.send(embed=result_embed)
                except:
                    pass
        else:
            await interaction.response.send_message("❌ Заявка не найдена")

class BaseCommands(app_commands.Group):
    def __init__(self):
        super().__init__(name='база', description='Базовые команды')
    
    @app_commands.command(name='set-beluga', description='Установить ID Beluga Develop')
    @app_commands.describe(user_id='Discord ID пользователя')
    async def set_beluga(self, interaction: discord.Interaction, user_id: str):
        if not await interaction.client.is_owner(interaction.user):
            await interaction.response.send_message("❌ Только владелец бота!", ephemeral=True)
            return
        interaction.client.bl_system.set_beluga_id(user_id)
        await interaction.response.send_message(f"✅ ID Beluga установлен: `{user_id}`")
    
    @app_commands.command(name='myid', description='Узнать свой Discord ID')
    async def myid(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"👤 **{interaction.user.name}**\n🆔 ID: `{interaction.user.id}`")
    
    @app_commands.command(name='пинг', description='Проверить задержку бота')
    async def ping(self, interaction: discord.Interaction):
        latency = round(interaction.client.latency * 1000)
        await interaction.response.send_message(f"⚡ Понг! **{latency}мс**")
    
    @app_commands.command(name='статистика', description='Общая статистика системы')
    @check_staff()
    async def stats(self, interaction: discord.Interaction):
        bl = interaction.client.bl_system
        stats = bl.get_statistics()
        active = len(bl.all_active())
        
        embed = discord.Embed(title="📊 СТАТИСТИКА СИСТЕМЫ ЧС", color=0x3498db)
        embed.add_field(name="🔥 Выдано ЧС", value=str(stats['total_issued']), inline=True)
        embed.add_field(name="🔓 Снято ЧС", value=str(stats['total_removed']), inline=True)
        embed.add_field(name="🟢 Активных", value=str(active), inline=True)
        embed.add_field(name="📝 Обжалований", value=str(stats['total_appeals']), inline=True)
        embed.add_field(name="✅ Одобрено", value=str(stats['accepted_appeals']), inline=True)
        embed.add_field(name="❌ Отклонено", value=str(stats['rejected_appeals']), inline=True)
        await interaction.response.send_message(embed=embed)

# ═══════════════ КЛАСС БОТА ═══════════════
class BlacklistBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
        self.bl_system = BlacklistSystem()
    
    async def setup_hook(self):
        # ИСПРАВЛЕНО #1: все команды регистрируются через self.tree.add_command()
        self.tree.add_command(BlacklistCommands())
        self.tree.add_command(ModeratorCommands())
        self.tree.add_command(AppealCommands())
        self.tree.add_command(BaseCommands())
        await self.tree.sync()
        self.check_expired_loop.start()
    
    @tasks.loop(minutes=5)
    async def check_expired_loop(self):
        if self.bl_system:
            self.bl_system.check_expired()
    
    @check_expired_loop.before_loop
    async def before_check(self):
        await self.wait_until_ready()

# ═══════════════ СОЗДАЕМ БОТА ═══════════════
bot = BlacklistBot()

# ═══════════════ ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ═══════════════
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    
    # Обработка апелляций в ЛС
    if isinstance(message.channel, discord.DMChannel):
        bl = bot.bl_system
        blacklist = bl.get_blacklist(message.author.id)
        
        if blacklist:
            appeal, status = bl.add_appeal(message.author.id, message.content)
            
            if status == 'cooldown':
                await message.channel.send("⚠️ Вы слишком часто подаете обжалования. Подождите немного.")
            else:
                await message.channel.send(f"✅ Ваше обжалование #{appeal['appeal_id']} принято! Модераторы рассмотрят его в ближайшее время.")
                await send_appeal_notification(bot, appeal)
        else:
            await message.channel.send("✅ У вас нет активного ЧС. Если у вас есть вопросы, обратитесь к администрации.")
    
    # ИСПРАВЛЕНО #3: обрабатываем обычные команды с префиксом
    await bot.process_commands(message)

# ═══════════════ СОБЫТИЕ ГОТОВНОСТИ ═══════════════
@bot.event
async def on_ready():
    print(f"""
╔══════════════════════════════════════════╗
║ ✅ БОТ УСПЕШНО ЗАПУЩЕН!
║ 🤖 Имя: {bot.user.name}
║ 🆔 ID: {bot.user.id}
║ 🌍 Серверов: {len(bot.guilds)}
║ 📊 Система ЧС активна
╚══════════════════════════════════════════╝
    """)
    print("📋 Доступные команды:")
    print("  🔹 /база set-beluga <ID> - установить себя как Beluga")
    print("  🔹 /модер добавить <пользователь> - добавить модератора")
    print("  🔹 /модер удалить <пользователь> - удалить модератора")
    print("  🔹 /чс выдать <пользователь> <срок> <причина> - выдать ЧС")
    print("  🔹 /чс снять <пользователь> - снять ЧС")
    print("  🔹 /чс список - список всех ЧС")
    print("  🔹 /чс инфо <пользователь> - информация о пользователе")
    print("  🔹 /обжаловать список - список обжалований")
    print("  🔹 /обжаловать рассмотреть <номер> <решение> - рассмотреть обжалование")
    print("  🔹 /база статистика - общая статистика")
    print("  🔹 /база пинг - проверить задержку")
    print("  🔹 /база myid - узнать свой ID")
    print("\n📩 ДЛЯ ОБЖАЛОВАНИЯ: просто напишите боту в ЛС ЛЮБОЕ сообщение!")

# ═══════════════ ФУНКЦИЯ ВВОДА ТОКЕНА (ИСПРАВЛЕНО #2) ═══════════════
def get_token_with_save():
    saved_token = load_token()
    if saved_token:
        print(f"\n{EMOJIS['info']} Найден сохраненный токен!")
        print(f"1. {EMOJIS['info']} Использовать сохраненный токен")
        print(f"2. {EMOJIS['new']} Использовать новый токен")
        choice = input("\nВыберите вариант (1 или 2): ").strip()
        if choice == '1':
            print(f"\n{EMOJIS['success']} Использую сохраненный токен")
            return saved_token
        elif choice == '2':
            new_token = input("Введите новый токен: ").strip()
            if new_token:
                save_token(new_token)
                print(f"{EMOJIS['success']} Новый токен сохранен!")
                return new_token
            else:
                print(f"{EMOJIS['warning']} Токен не введен, использую сохраненный")
                return saved_token
        else:
            print(f"{EMOJIS['warning']} Неверный выбор, использую сохраненный")
            return saved_token
    else:
        print(f"\n{EMOJIS['info']} Сохраненный токен не найден")
        new_token = input("Введите токен бота: ").strip()
        if new_token:
            save_token(new_token)
            print(f"{EMOJIS['success']} Токен сохранен!")
            return new_token
        else:
            print(f"{EMOJIS['error']} Токен не введен!")
            return None

# ═══════════════ ЗАПУСК ═══════════════
if __name__ == "__main__":
    print("\n" + "="*50)
    print("BELUGA BOT - СИСТЕМА ЧС v3.0")
    print("="*50)
    
    token = get_token_with_save()
    if not token:
        print("\n❌ Невозможно запустить бота без токена!")
        input("\nНажмите Enter для выхода...")
        sys.exit(1)
    
    print("\n🚀 Запуск бота...\n")
    
    try:
        bot.run(token)
    except discord.LoginFailure:
        print("\n❌ Неверный токен!")
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
            print("🗑️ Неверный токен удален из сохранения")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
    finally:
        input("\nНажмите Enter для выхода...")