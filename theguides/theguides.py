__author__ = "Felix"

import asyncio
import csv
import json
import math
import os
import re
import uuid
from datetime import datetime, timedelta
from difflib import SequenceMatcher

import aiohttp
import aiopg
import core
import discord
import psycopg2
from discord.ext import commands, tasks

# PULL REQUEST TO CHANGE THESE
BYPASS_LIST = [
    767824073186869279, # abbi
    249568050951487499, # akhil
    323473569008975872, # olly
    381170131721781248, # crois
    346382745817055242, # felix
    211368856839520257, # illy

]

UNITS = {
    's': 'seconds',
    'm': 'minutes',
    'h': 'hours',
    'd': 'days',
    'w': 'weeks'
}

BLOXLINK_API_KEY = os.environ.get('BLOXLINK_KEY')
SERVER_ID = "788228600079843338"
HEADERS = {'Authorization': BLOXLINK_API_KEY}

PASSWORD = os.environ.get('POSTGRES_PASSW')

EMOJI_VALUES = {True: "✅", False: "⛔"}
K_VALUE = 0.099

dsn = f"dbname=tickets user=cityairways password={PASSWORD} host=citypostgres"


async def rank_users_by_tickets_this_month_to_csv(pool, ctx):
    filename = f"monthly_ranking_{uuid.uuid4()}.csv"
    # Fetch the ranking data
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT user_id,
                       COUNT(*) AS ticket_count,
                       RANK() OVER (ORDER BY COUNT(*) DESC) AS rank
                FROM tickets
                WHERE DATE_TRUNC('month', timestamp) = DATE_TRUNC('month', CURRENT_DATE)
                GROUP BY user_id
                ORDER BY ticket_count DESC;
            """)
            results = await cur.fetchall()

    results = [list(i) for i in results]

    print("CSV Generation requested, starting conversion for ROBLOX Usernames")

    time = unix_converter(2.3 * len(results))

    msg = await ctx.reply(
        f"Started generation, estimated completion: <t:{time}:R>")

    rm = []

    for j, i in enumerate(results):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    f"https://api.blox.link/v4/public/guilds/788228600079843338/discord-to-roblox/{i[0]}",
                    headers=HEADERS) as res:
                await asyncio.sleep(1)
                roblox_data = await res.json()
                if "error" in roblox_data:
                    if roblox_data["error"] == "Unknown Member":
                        await ctx.channel.send(
                            f"Discord ID: {i[0]} not in discord, <@{i[0]}> will not be included in pay, but if you need his ticket amount it is: `{i[1]}`"
                        )
                        print(f"{i[0]} NOT IN DISCORD, NOT INCLUDED IN CSV")
                        rm.append(j)
                        continue
                try:
                    roblox_name = roblox_data["resolved"]["roblox"]["name"]
                except Exception as e:
                    await ctx.channel.send(
                        f"Discord ID: {i[0]} giving me an error, <@{i[0]}> will not be included in pay, but if you need his ticket amount it is: `{i[1]}`"
                    )
                    print(f"{i[0]} NOT IN DISCORD, NOT INCLUDED IN CSV")
                    rm.append(j)
                    continue
                i[0] = roblox_name

    rm_set = set(rm)
    results = [item for idx, item in enumerate(results) if idx not in rm_set]

    # Write results to a CSV file
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["ROBLOX Username", "Ticket Count", "Rank"])
        for row in results:
            writer.writerow(row)
    await msg.delete()

    return filename


async def create_database():
    pool = await aiopg.create_pool(dsn)

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Create the table
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Create indexes
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON tickets(timestamp);"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_id ON tickets(user_id);")

    return pool


async def count_user_tickets_this_month(pool, user_id):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Execute the query with user_id as a parameter
            await cur.execute(
                """
                SELECT COUNT(*) 
                FROM tickets 
                WHERE user_id = %s
                AND DATE_TRUNC('month', timestamp) = DATE_TRUNC('month', CURRENT_DATE);
            """, (user_id, ))
            # Fetch the result
            result = await cur.fetchone()
            # Return the count
            return result[0]

async def count_user_tickets_today(pool, user_id):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Execute the query with user_id as a parameter
            await cur.execute(
                """
                SELECT COUNT(*) 
                FROM tickets 
                WHERE user_id = %s
                AND DATE(timestamp) = CURRENT_DATE;
                """, (user_id,))
            # Fetch the result
            result = await cur.fetchone()
            # Return the count
            return result[0]


async def count_user_tickets_this_week(pool, user_id):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Execute the query with user_id as a parameter
            await cur.execute(
                """
                SELECT COUNT(*) 
                FROM tickets 
                WHERE user_id = %s
                AND DATE_TRUNC('week', timestamp) = DATE_TRUNC('week', CURRENT_DATE);
            """, (user_id, ))
            # Fetch the result
            result = await cur.fetchone()
            # Return the count
            return result[0]


async def add_tickets(pool, user_id):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO tickets (user_id)
                VALUES (%s);
                """, (user_id, ))


async def get_tickets_in_timeframe(pool, user_id, days):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COUNT(*) FROM tickets
                WHERE user_id = %s AND timestamp >= NOW() - INTERVAL '%s days';
                """, (user_id, days))
            result = await cur.fetchone()
            return result[0]


def handle_cooldown_result(future, ctx):
    cooldown = future.result()
    # Return the appropriate Cooldown object
    if cooldown is not None:
        return commands.Cooldown(1, cooldown)
    return None


def new_cooldown(ctx):
    if ctx.author.id in BYPASS_LIST:
       return None

    print(f"cooldown")
    cooldown = get_cooldown_time_sync(ctx.bot.sync_db, ctx)
    print(f"cooldown {cooldown}")

    return commands.Cooldown(1, cooldown) if cooldown is not None else None


"""
Ready to be implemented with @commands.dynamic_cooldown(new_cooldown, type=commands.BucketType.user)
"""


def get_cooldown_time_sync(pool, ctx):
    try:
        user_id = ctx.author.id
    except Exception:
        user_id = ctx

    print("yo")
    conn = pool
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM tickets WHERE user_id = %s AND DATE_TRUNC('week', timestamp) = DATE_TRUNC('week', CURRENT_DATE)",
        (user_id, ))
    tickets = cursor.fetchone()[0]

    cursor.close()

    if tickets < 5:
        return 0
    if 5 <= tickets < 36.6:
        time = math.exp(K_VALUE * tickets)
    else:
        time = math.exp(K_VALUE * 36.6)

    time *= 60

    return time


async def get_cooldown_time(pool, ctx, mew=False):
    try:
        user_id = ctx.author
    except Exception:
        user_id = ctx
    tickets = await count_user_tickets_this_week(pool, user_id)

    if mew is True:
        tickets -= 1

    if tickets < 5:
        return 0
    if 5 <= tickets < 36.6:
        time = math.exp(K_VALUE * tickets)
    else:
        time = math.exp(K_VALUE * 36.6)

    time *= 60

    return time


def unix_converter(seconds: int) -> int:
    now = datetime.now()
    then = now + timedelta(seconds=seconds)

    return int(then.timestamp())


def convert_to_seconds(text: str) -> int:
    return int(
        timedelta(
            **{
                UNITS.get(m.group('unit').lower(), 'seconds'):
                float(m.group('val'))
                for m in re.finditer(r'(?P<val>\d+(\.\d+)?)(?P<unit>[smhdw]?)',
                                     text.replace(' ', ''),
                                     flags=re.I)
            }).total_seconds())


channel_options = {
    'Main': '1221162035513917480',
    'Prize Claims': '1213885924581048380',
    'Affiliate': '1196076391242944693',
    'Development': '1196076499137200149',
    'Appeals': '1196076578938036255',
    'Moderator Reports': '1246863733355970612'
}

# Dummy code for testing
# channel_options = {
#     'Mu': '1249441110829301911',
#     'Phi': '1249441160762494997',
#     'Lambaaaa': '1249441131524132894',
# }


class DropDownChannels(discord.ui.Select):

    def __init__(self):
        options = [
            discord.SelectOption(label=i[0]) for i in channel_options.items()
        ]

        super().__init__(
            placeholder="Select a channel...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction):
        category_id = channel_options[self.values[0]]
        category = interaction.guild.get_channel(int(category_id))

        await interaction.channel.edit(category=category,
                                       sync_permissions=True)

        await interaction.response.edit_message(
            content="Moved channel successfully, thank the guides", view=None)


class DropDownView(discord.ui.View):

    def __init__(self, dropdown):
        super().__init__()
        self.add_item(dropdown)


THUMBNAIL = "https://cdn.discordapp.com/attachments/1208495821868245012/1291896171555455027/CleanShot_2024-10-04_at_23.53.582x.png?ex=6701c391&is=67007211&hm=1138ae2d92387ecde7be34af238bd756462970de2ca6ca559c6aa091f932a8ae&"
FOOTER = "Sponsored by the Guides Committee"

gamepasses = {
    "Rainbow Name": 20855496,
    "Ground Crew": 20976711,
    "Cabin Crew": 20976738,
    "Captain": 20976820,
    "Senior Staff": 20976845,
    "Staff Manager": 20976883,
    "Airport Manager": 20976943,
    "Board of Directors": 21002253,
    "Co Owner": 21002275,
    "First Class": 21006608,
    "Segway Board": 22042259
}

# MONOKAI PRO PALETTE
colours = {
    "green": 0xA9DC76,
    "red": 0xFF6188,
    "yellow": 0xFFD866,
    "light_blue": 0x78DCE8,
    "purple": 0xAB9DF2
}


def find_most_similar(name):
    return max(gamepasses.items(),
               key=lambda x: SequenceMatcher(None, x[0], name).ratio())


def EmbedMaker(ctx, **kwargs):
    if "colour" not in kwargs:
        color = 0x8e00ff
    else:
        color = colours[kwargs["colour"].lower()]
        del kwargs["colour"]
    e = discord.Embed(**kwargs, colour=color)
    #   e.set_image(url=THUMBNAIL)
    e.set_footer(
        text="City Airways",
        icon_url=
        "https://cdn.discordapp.com/icons/788228600079843338/21fb48653b571db2d1801e29c6b2eb1d.png?size=4096"
    )
    return e

ROLE_HIERARCHY = [
    '1248340570275971125', '1248340594686820403', '1248340609727729795',
    '1248340626773381240', '1248340641117765683'
]

def is_bypass():

    async def predicate(ctx):
        return (ctx.author.id in BYPASS_LIST) or (set(
            [i.id
             for i in ctx.author.roles]).intersection(set(ROLE_HIERARCHY[:2])))

    return commands.check(predicate)


async def check(ctx):
    if ctx.author.id in BYPASS_LIST or set(
        [i.id
         for i in ctx.author.roles]).intersection(set(ROLE_HIERARCHY[:2])):
        return True

    coll = ctx.bot.plugin_db.get_partition(ctx.bot.get_cog('GuidesCommittee'))
    thread = await coll.find_one({'thread_id': str(ctx.thread.channel.id)})
    if thread is not None:
        can_r = ctx.author.bot or str(ctx.author.id) == thread['claimer']
        if not can_r:
            if "⛔" not in [i.emoji for i in ctx.message.reactions
                           ]:  # Weird bug where check runs twice?????
                await ctx.message.add_reaction("⛔")
        return can_r
    # cba to do this properly so repetition it is
    if "⛔" not in [i.emoji for i in ctx.message.reactions
                   ]:  # Weird bug where check runs twice?????
        await ctx.message.add_reaction("⛔")
    return False


class GuidesCommittee(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.db = self.bot.api.get_plugin_partition(self)
        self.bot.get_command("reply").add_check(check)
        self.bot.get_command("areply").add_check(check)
        self.bot.get_command("fareply").add_check(check)
        self.bot.get_command("freply").add_check(check)
        self.bot.get_command("close").add_check(check)
        self.db_generated = False

        # Synchronous database, I hate this, but Oliver made me do a fucking cooldown
        self.bot.sync_db = psycopg2.connect(dbname="tickets",
                                            user="cityairways",
                                            password=PASSWORD,
                                            host="citypostgres")

    async def cog_command_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            embed = EmbedMaker(
                ctx,
                title="On Cooldown",
                description=
                f"You can use this command again <t:{unix_converter(error.retry_after)}:R>",
                colour="red")

            await ctx.send(embed=embed)
        else:
            # TAKEN FROM https://github.com/modmail-dev/Modmail/blob/master/bot.py
            if isinstance(error, (commands.BadArgument, commands.BadUnionArgument)):
                await ctx.typing()
                await ctx.send(embed=discord.Embed(color=ctx.bot.error_color, description=str(error)))
            elif isinstance(error, commands.CommandNotFound):
                print("CommandNotFound: %s", error)
            elif isinstance(error, commands.MissingRequiredArgument):
                await ctx.send_help(ctx.command)
            elif isinstance(error, commands.CheckFailure):
                for check in ctx.command.checks:
                    if not await check(ctx):
                        if hasattr(check, "fail_msg"):
                            await ctx.send(
                                embed=discord.Embed(color=ctx.bot.error_color, description=check.fail_msg)
                            )
                        if hasattr(check, "permission_level"):
                            corrected_permission_level = ctx.bot.command_perm(ctx.command.qualified_name)
                            print(
                                "User %s does not have permission to use this command: `%s` (%s).",
                                ctx.author.name,
                                ctx.command.qualified_name,
                                corrected_permission_level.name,
                            )
                print("CheckFailure: %s", error)
            elif isinstance(error, commands.DisabledCommand):
                print("DisabledCommand: %s is trying to run eval but it's disabled", ctx.author.name)
            elif isinstance(error, commands.CommandInvokeError):
                await ctx.send(
                    embed=discord.Embed(color=ctx.bot.error_color, description=f"{str(error)}\nYou might be getting this error during **getinfo** if the user is either\n1. Not in the `main` server\n2. Has no linked account in bloxlink")
                )
            else:
                await ctx.channel.send(f"{error}, {type(error)}")
                print("Unexpected exception:", error)

            try:
                await ctx.message.clear_reactions()
                await ctx.message.add_reaction("⛔")
            except Exception:
                pass

    @commands.command()
    async def initdb(self, ctx):
        if self.db_generated is False:
            pool = await create_database()
            self.bot.pool = pool
            await ctx.reply("Generated postgres pool")
            self.db_generated = True
        else:
            await ctx.reply("Postgres pool is already generated")

    @core.checks.thread_only()
    @core.checks.has_permissions(core.models.PermissionLevel.SUPPORTER)
    @commands.dynamic_cooldown(new_cooldown, type=commands.BucketType.user)
    @commands.command()
    async def claim(self, ctx):
        thread = await self.db.find_one(
            {'thread_id': str(ctx.thread.channel.id)})
        if thread is None:
            await self.db.insert_one({
                'thread_id': str(ctx.thread.channel.id),
                'claimer': str(ctx.author.id),
                'original_name': ctx.channel.name
            })

            try:
                nickname = ctx.author.display_name
                await ctx.channel.edit(name=f"claimed-{nickname}") # pls dont abuse this

                embed = EmbedMaker(
                    ctx,
                    title="Claimed",
                    description=f"Claimed by {ctx.author.mention}",
                    colour="green")
                await ctx.message.channel.send(embed=embed)

            except discord.errors.Forbidden:
                await ctx.message.reply("I don't have permission to do that")
        else:
            claimer = thread['claimer']
            embed = EmbedMaker(
                ctx,
                title="Already Claimed",
                description=
                f"Already claimed by {(f'<@{claimer}>') if claimer != ctx.author.id else 'you, dumbass'}",
                colour="red")
            await ctx.send(embed=embed)

    @commands.command()
    async def tickets(self, ctx, user: discord.Member, days: int):
        tickets = await get_tickets_in_timeframe(self.bot.pool, user.id, days)
        return await ctx.reply(
            f"{tickets} {'tickets' if tickets > 1 else 'ticket'} in last {days} days"
        )

    @core.checks.thread_only()
    @core.checks.has_permissions(core.models.PermissionLevel.SUPPORTER)
    @commands.command()
    async def unclaim(self, ctx):
        thread = await self.db.find_one(
            {'thread_id': str(ctx.thread.channel.id)})
        if thread is None:
            embed = EmbedMaker(
                ctx,
                title="Already Unclaimed",
                description="This thread is not claimed, you can claim it!")
            return await ctx.message.reply(embed=embed)

        if thread['claimer'] == str(ctx.author.id):
            await self.db.find_one_and_delete(
                {'thread_id': str(ctx.thread.channel.id)})

            try:
                embed = EmbedMaker(
                    ctx,
                    title="Unclaimed",
                    description=f"Unclaimed by {ctx.author.mention}",
                    colour="green")

                await ctx.channel.edit(name=thread['original_name'])

                await ctx.message.reply(embed=embed)

            except discord.errors.Forbidden:
                await ctx.message.reply("I don't have permission to do that")
        else:
            e = discord.Embed(
                title="Unclaim Denied",
                description=
                f"You're not the claimer of this thread, don't anger chairwoman abbi"
            )
            await ctx.message.reply(embed=e)

    @core.checks.has_permissions(core.models.PermissionLevel.MODERATOR)
    @commands.command()
    async def export(self, ctx):
        await ctx.message.add_reaction("<a:loading_f:1249799401958936576>")
        file = await rank_users_by_tickets_this_month_to_csv(
            self.bot.pool, ctx)
        await ctx.message.clear_reactions()
        with open(file, 'rb') as f:
            await ctx.send(file=discord.File(f, filename=file))

    @core.checks.thread_only()
    @core.checks.has_permissions(core.models.PermissionLevel.SUPPORTER)
    @commands.command()
    async def takeover(self, ctx):
        roles_taker = [str(i.id) for i in ctx.author.roles]
        roles_to_take_t = []
        for i in range(len(roles_taker)):
            if roles_taker[i] not in ROLE_HIERARCHY:
                roles_to_take_t.append(roles_taker[i])

        for i in roles_to_take_t:
            roles_taker.remove(i)

        # await asyncio.sleep(1)
        thread = await self.db.find_one(
            {'thread_id': str(ctx.thread.channel.id)})

        if thread['claimer'] == str(ctx.author.id):
            embed = EmbedMaker(
                ctx,
                title="Takeover Denied",
                description=
                f"You have literally claimed this yourself tf u doing",
                colour="red")
            await ctx.channel.send(embed=embed)
            return

        mem = ctx.guild.get_member(thread['claimer'])

        if mem is None:
            mem = await ctx.guild.fetch_member(thread['claimer'])

        roles_claimed = [str(i.id) for i in mem.roles]

        roles_to_take_c = []
        for i in range(len(roles_claimed)):
            if roles_claimed[i] not in ROLE_HIERARCHY:
                roles_to_take_c.append(roles_claimed[i])

        for i in roles_to_take_c:
            roles_claimed.remove(i)

        if (ROLE_HIERARCHY.index(roles_taker[-1])
                < ROLE_HIERARCHY.index(roles_claimed[-1])):
            await self.db.find_one_and_update(
                {'thread_id': str(ctx.thread.channel.id)},
                {'$set': {
                    'claimer': str(ctx.author.id)
                }})
            e = EmbedMaker(
                ctx,
                title="Taken over succesfully",
                description=f"Takeover by <@{ctx.author.id}> successful, they now own the ticket. Channel name change can take up to 5 minutes")
            await ctx.channel.send(embed=e)
            try:
                nickname = ctx.author.display_name
                await ctx.channel.edit(name=f"claimed-{nickname}")
            except discord.errors.Forbidden:
                await ctx.message.reply("I couldn't change the channel name sorry")
        else:
            e = EmbedMaker(
                ctx,
                title="Takeover Denied",
                description=
                f"Takeover denied since the claimer is your superior or the same rank as you, if you need to takeover and this is not letting you, ask management for a manual transfer."
            )
            await ctx.reply(embed=e)

    async def cog_unload(self):
        cmds = [
            self.bot.get_command("reply"),
            self.bot.get_command("freply"),
            self.bot.get_command("areply"),
            self.bot.get_command("fareply"),
            self.bot.get_command("close")
        ]
        for i in cmds:
            if check in i.checks:
                print(f'REMOVING CHECK IN {i.name}')  # Some logging yh
                i.remove_check(check)

        self.bot.sync_db.close()
        await self.bot.pool.terminate()

    @commands.command()
    @core.checks.has_permissions(core.models.PermissionLevel.SUPPORTER)
    async def owns(self, ctx, username, *, gamepass):
        conversion_gamepass = False
        conversion_username = False

        try:
            gamepass = int(gamepass)
        except Exception:
            gamepass = gamepass
            conversion_gamepass = True

        try:
            username_id = int(username)
        except Exception:
            username = username
            conversion_username = True

        async with aiohttp.ClientSession() as session:
            if conversion_username is True:
                async with session.post(
                        'https://users.roblox.com/v1/usernames/users',
                        data=json.dumps({
                            'usernames': [username],
                            'excludeBannedUsers': True
                        })) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if bool(data['data']) is False:
                            e = EmbedMaker(
                                ctx,
                                title="Wrong username",
                                description=
                                "Please try putting the right **ROBLOX** username"
                            )
                            return await ctx.message.reply(embed=e)
                        if data['data'][0]['requestedUsername'] != username:
                            e = EmbedMaker(
                                ctx,
                                title="Failed checks",
                                description=
                                "Error Checking, please try again")
                            return await ctx.message.reply(embed=e)
                        print(data['data'][0]['id'])
                        username_id = data['data'][0]['id']

            if conversion_gamepass is True:
                gamepass_id = find_most_similar(gamepass)

            async with session.get(
                    f'https://inventory.roblox.com/v1/users/{username_id}/items/1/{gamepass_id[1]}/is-owned'
            ) as resp:
                if resp.status == 200:
                    owns = await resp.json()

                    if not isinstance(owns, bool):
                        if "errors" in owns.keys():
                            owns = False

                    if owns is True:
                        e = EmbedMaker(
                            ctx,
                            title=f"{EMOJI_VALUES[True]} Ownership Verified",
                            description=
                            f"{gamepass_id[0]} owned by {username}, [link](https://inventory.roblox.com/v1/users/{username_id}/items/1/{gamepass_id[1]}/is-owned)"
                        )
                        return await ctx.message.reply(embed=e)
                    else:
                        e = EmbedMaker(
                            ctx,
                            title=f"{EMOJI_VALUES[False]} Gamepass NOT Owned",
                            description=
                            f"{gamepass_id[0]} **NOT** owned by {username}, [link](https://inventory.roblox.com/v1/users/{username_id}/items/1/{gamepass_id[1]}/is-owned)"
                        )
                        return await ctx.message.reply(embed=e)

    @commands.command()
    @core.checks.thread_only()
    async def getinfo(self, ctx, member: discord.Member = None):
        await ctx.message.add_reaction("<a:loading_f:1249799401958936576>")

        if member is None:
            m_id = ctx.thread.recipient.id
        else:
            m_id = member.id
        gamepasses_owned = {key: "IDK" for key in gamepasses.keys()}

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                        f"https://api.blox.link/v4/public/guilds/788228600079843338/discord-to-roblox/{m_id}",
                        headers=HEADERS) as res:
                    roblox_data = await res.json()
                    roblox_id = roblox_data["robloxID"]

                    # await ctx.channel.send(roblox_data)

                    avatar_url_get = roblox_data["resolved"]["roblox"][
                        "avatar"]["bustThumbnail"]
            except Exception as e:
                raise e
            async with session.get(avatar_url_get) as res:
                avatar_url_ = await res.json()
                avatar_url = avatar_url_["data"][0]["imageUrl"]

            for i in gamepasses_owned.keys():
                id = gamepasses[i]

                async with session.get(
                        f'https://inventory.roblox.com/v1/users/{roblox_id}/items/1/{id}/is-owned'
                ) as res:
                    owns = await res.json()

                    if not isinstance(owns, bool):
                        if "errors" in owns.keys():
                            owns = False

                    if owns is True:
                        gamepasses_owned[i] = True
                    else:
                        gamepasses_owned[i] = False

        # Past Usernames
        past_usernames = []
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    f"https://users.roblox.com/v1/users/{roblox_data['robloxID']}/username-history"
            ) as r:
                response = await r.json()

                if "errors" in response.keys():
                    raise KeyError

                past_usernames = [i['name'] for i in response['data']]

        roblox_name = roblox_data["resolved"]["roblox"]["name"]
        roblox_display_name = roblox_data["resolved"]["roblox"]["displayName"]
        roblox_profile_link = roblox_data["resolved"]["roblox"]["profileLink"]
        roblox_rank_name = roblox_data["resolved"]["roblox"]["groupsv2"][
            "8619634"]["role"]["name"]
        roblox_rank_id = roblox_data["resolved"]["roblox"]["groupsv2"][
            "8619634"]["role"]["rank"]

        embed = discord.Embed(title=roblox_name,
                              url=roblox_profile_link,
                              colour=0x8e00ff,
                              timestamp=datetime.now())

        msg = ""
        for i, j in gamepasses_owned.items():
            msg += f"**{i}**: {EMOJI_VALUES[j]}\n"

        msg.strip()

        embed.add_field(
            name="Discord",
            value=
            f"**ID**: {m_id}\n**Username**: {ctx.thread.recipient.name}\n**Display Name**: {ctx.thread.recipient.display_name}",
            inline=False)
        embed.add_field(
            name="ROBLOX",
            value=
            f"**ID**: {roblox_id}\n**Username**: {roblox_name}\n**Display Name**: {roblox_display_name}\n**Rank In Group**: {roblox_rank_name} ({roblox_rank_id})",
            inline=False)

        embed.add_field(name="ROBLOX PAST USERNAMES",
                        value="None" if len(past_usernames) == 0 else
                        "\n".join(past_usernames),
                        inline=False)
        embed.add_field(name="Gamepasses", value=msg, inline=False)

        embed.set_thumbnail(url=avatar_url)

        embed.set_footer(
            text=FOOTER,
            icon_url=
            "https://cdn.discordapp.com/attachments/1208495821868245012/1249743898075463863/Logo.png?ex=66686a34&is=666718b4&hm=f13b57e1fbd96c14bc8123d0a57980791e0f0db267da9ae39911fe50211406e1&"
        )

        await ctx.message.clear_reactions()

        await ctx.reply(embed=embed)

    @commands.command()
    @core.checks.thread_only()
    @core.checks.has_permissions(core.models.PermissionLevel.SUPPORTER)
    async def mover(self, ctx):
        view = DropDownView(DropDownChannels())

        await ctx.send("Choose a channel to move this ticket to", view=view)

    @commands.command()
    @core.checks.thread_only()
    @core.checks.has_permissions(core.models.PermissionLevel.SUPPORTER)
    async def remindme(self, ctx, time: str, *, message: str):
        embed = EmbedMaker(
            ctx,
            title="Remind Me",
            description=f"I will remind you about {message} in {time}")
        m = await ctx.message.reply(embed=embed)

        await asyncio.sleep(convert_to_seconds(time))

        await ctx.channel.send(f"<@{ctx.author.id}>, {message}")

        try:
            await m.delete()
            await ctx.author.send(message)
        except discord.errors.Forbidden:
            pass

    @commands.command()
    @core.checks.thread_only()
    @is_bypass()
    async def transfer(self, ctx, user: discord.Member):
        thread = await self.db.find_one(
            {'thread_id': str(ctx.thread.channel.id)})

        if thread['claimer'] == str(user.id):
            embed = EmbedMaker(
                ctx,
                title="Transfer Denied",
                description=f"<@{user.id}> is the thread claimer")
            await ctx.channel.send(embed=embed)
            return

        await self.db.find_one_and_update(
            {'thread_id': str(ctx.thread.channel.id)},
            {'$set': {
                'claimer': str(user.id)
            }})
        e = EmbedMaker(ctx,
                       title="Transfer",
                       description=f"Transfer by <@{user.id}> successful, this ticket is now theirs.")
        await ctx.channel.send(embed=e)
        try:
            nickname = user.display_name

            await ctx.channel.edit(name=f"claimed-{nickname}")

            m = await ctx.message.channel.send(
                f"Successfully renamed, this rename was sponsored by the **guides committee**"
            )

            await asyncio.sleep(10)

            await m.delete()
        except Exception as e:
            return await ctx.message.channel.send(str(e))

    @commands.Cog.listener()
    async def on_thread_close(self, thread, closer, silent, delete_channel,
                              message, scheduled):
        if self.db_generated is False:
            pool = await create_database()
            self.bot.pool = pool
            self.db_generated = True

        channel = closer.dm_channel

        if channel is None:
            channel = await closer.create_dm()

        if thread.recipient.id == closer.id:
            try:
                return await channel.send(
                    "You closed your own ticket, it will not count towards your ticket count. A copy of this message is sent to management."
                )
            except discord.errors.Forbidden:
                return
        await add_tickets(self.bot.pool, closer.id)
        week = await count_user_tickets_this_week(self.bot.pool, closer.id)
        month = await count_user_tickets_this_month(self.bot.pool, closer.id)
        day = await count_user_tickets_today(self.bot.pool, closer.id)
        print(f"Added 1 ticket to {closer} ({closer.id}")

        cooldown = await get_cooldown_time(self.bot.pool, closer.id, True)

        try:
            await channel.send(
                f"Congratulations on closing your ticket {closer}. This is your ticket number `{day}` today, your ticket number`{week}` this week and your ticket number `{month}` this month. Your cooldown is: `{cooldown:.1f}` seconds"
            )
            if str(closer.id) == "1208702357425102880":
                await channel.send(
                    "Hi Ben, this is a special message I have in store for when you close a ticket. I just want to extend my heartfelt congratulations, because this job you do is impressive."
                )

            if day == 8:
                await channel.send("⚠**TICKET 8 WARNING**⚠\nClosing your 9th ticket will send a message to management where warnings/strikes/demotions might take place, if you have tickets currently claimed **UNCLAIM THEM**")

            if day > 8:
                channel = await self.bot.fetch_channel(1311111724379672608)
                await channel.send(f"⚠**MORE THAN 8 WARNING**⚠\n<@{closer.id}> closed more than 8 tickets in a day. This is his ticket number `{day}` today\n\n@everyone")
        except discord.errors.Forbidden:
            pass

    @commands.command()
    @is_bypass()
    async def hi(self, ctx):
        await ctx.channel.send("Hi there")


async def setup(bot):
    await bot.add_cog(GuidesCommittee(bot))
