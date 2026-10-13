import discord
from discord.ext import commands
from discord import app_commands
import json, os, asyncio, random, string, aiohttp, io, base64
from datetime import datetime
from dotenv import load_dotenv
from aiohttp import web
from supabase import create_client, Client
from PIL import Image, ImageDraw, ImageFont

load_dotenv()

TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", 0))
CANAL_LOGS = int(os.getenv("CANAL_LOGS", 0))
CANAL_ENTREGAS = int(os.getenv("CANAL_ENTREGAS", 0))
CATEGORIA_TICKETS = int(os.getenv("CATEGORIA_TICKETS", 0))
CARGOS_STAFF = [int(x) for x in os.getenv("CARGOS_STAFF", "").split(",") if x]

SHARPIFY_ID = os.getenv("SHARPIFY_CLIENT_ID", "")
SHARPIFY_SECRET = os.getenv("SHARPIFY_CLIENT_SECRET", "")
SHARPIFY_BASE = os.getenv("SHARPIFY_GATEWAY_URL", "https://sharpify-pay.com")
SHARPIFY_WEBHOOK_SECRET = os.getenv("SHARPIFY_WEBHOOK_SECRET", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Supabase conectado")
    except Exception as e:
        print(f"❌ Erro Supabase: {e}")
else:
    print("⚠️ Supabase não configurado")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ═══════════════════════════════════════
#  PERSISTÊNCIA
# ═══════════════════════════════════════
_cache = {}

def _load_local(f, default):
    if not os.path.exists(f): return default
    try:
        with open(f, "r", encoding="utf-8") as x: return json.load(x)
    except: return default

def _save_local(f, d):
    try:
        with open(f, "w", encoding="utf-8") as x:
            json.dump(d, x, indent=4, ensure_ascii=False)
    except Exception as e: print(f"[Local] {f}: {e}")

def load(f, default):
    if f in _cache: return _cache[f]
    data = None
    if supabase:
        try:
            r = supabase.table("bot_state").select("value").eq("key", f).execute()
            if r.data and len(r.data) > 0:
                data = r.data[0]["value"]
        except Exception as e: print(f"[Supabase] load {f}: {e}")
    if data is None:
        data = _load_local(f, default)
    _cache[f] = data
    return data

def save(f, d):
    _cache[f] = d
    _save_local(f, d)
    if supabase:
        try:
            supabase.table("bot_state").upsert({
                "key": f, "value": d,
                "updated_at": datetime.now().isoformat()
            }).execute()
        except Exception as e: print(f"[Supabase] save {f}: {e}")

def get_config():     return load("config.json", {})
def get_catalogos():  return load("catalogos.json", {})
def get_produtos():   return load("produtos.json", {})
def get_pedidos():    return load("pedidos.json", [])
def get_tickets():    return load("tickets.json", {})
def get_seen():       return load("webhook_seen.json", [])
def get_postados():   return load("postados.json", {})

def set_config(c):    save("config.json", c)
def set_produtos(p):  save("produtos.json", p)
def set_pedidos(p):   save("pedidos.json", p)
def set_postados(p):  save("postados.json", p)

def is_staff(m): return any(r.id in CARGOS_STAFF for r in m.roles) or m.guild_permissions.administrator
def agora(): return datetime.now().strftime("%d/%m/%Y %H:%M")
def novo_id(): return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

def url_imagem_valida(url):
    if not url: return False
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")): return False
    ext = (".png", ".jpg", ".jpeg", ".gif", ".webp")
    return url.lower().endswith(ext) or "cdn.discordapp.com" in url or "i.imgur.com" in url or "media.discordapp.net" in url

# ═══════════════════════════════════════
#  GERAR IMAGEM DO RECIBO
# ═══════════════════════════════════════
async def gerar_recibo_imagem(pedido):
    try:
        W, H = 900, 950
        fundo = (15, 15, 18)
        vermelho = (220, 53, 69)
        vermelho_escuro = (90, 20, 25)
        branco = (245, 245, 245)
        cinza = (150, 150, 155)
        cinza_escuro = (35, 35, 40)

        img = Image.new("RGB", (W, H), fundo)
        draw = ImageDraw.Draw(img)

        f_titulo = f_grande = f_medio = f_normal = f_pequena = None
        for nome in ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                     "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]:
            try:
                f_titulo = ImageFont.truetype(nome, 28)
                f_grande = ImageFont.truetype(nome, 36)
                f_medio = ImageFont.truetype(nome, 22)
                f_normal = ImageFont.truetype(nome, 18)
                f_pequena = ImageFont.truetype(nome, 14)
                break
            except: continue
        if not f_titulo:
            f_titulo = f_grande = f_medio = f_normal = f_pequena = ImageFont.load_default()

        # Header
        draw.rectangle([(0, 0), (W, 90)], fill=vermelho_escuro)
        draw.rectangle([(0, 90), (W, 94)], fill=vermelho)
        draw.text((40, 30), "QZZ VENDAS COMMUNITY", font=f_titulo, fill=branco)
        draw.text((W - 100, 38), "APP", font=f_normal, fill=branco)

        # Avatar
        try:
            user = await bot.fetch_user(pedido["comprador_id"])
            avatar_bytes = await user.display_avatar.replace(size=128, format="png").read()
            avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((100, 100), Image.LANCZOS)
            mask = Image.new("L", (100, 100), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 100, 100), fill=255)
            img.paste(avatar, (40, 140), mask)
        except Exception as e:
            draw.ellipse([(40, 140), (140, 240)], fill=cinza_escuro)

        nome_cliente = pedido.get("comprador_nome", "Cliente")
        if len(nome_cliente) > 24: nome_cliente = nome_cliente[:24] + "..."
        draw.text((165, 155), nome_cliente, font=f_medio, fill=branco)
        draw.text((165, 195), f"ID: {pedido['comprador_id']}", font=f_pequena, fill=cinza)

        draw.text((40, 280), "COMPRA REALIZADA", font=f_grande, fill=vermelho)

        draw.text((40, 360), "CARRINHO", font=f_medio, fill=cinza)
        draw.line([(40, 395), (W - 40, 395)], fill=cinza_escuro, width=1)

        produto_txt = f"{pedido['produto_nome']}"
        if len(produto_txt) > 50: produto_txt = produto_txt[:50] + "..."
        draw.text((40, 415), produto_txt, font=f_normal, fill=branco)

        var_txt = f"└ {pedido['variacao_nome']}"
        if len(var_txt) > 50: var_txt = var_txt[:50] + "..."
        draw.text((40, 445), var_txt, font=f_pequena, fill=cinza)

        valor_txt = f"R$ {pedido['preco_final']:.2f}".replace(".", ",")
        bbox = draw.textbbox((0, 0), valor_txt, font=f_medio)
        w_txt = bbox[2] - bbox[0]
        draw.text((W - 40 - w_txt, 415), valor_txt, font=f_medio, fill=branco)

        draw.line([(W - 250, 480), (W - 40, 480)], fill=cinza_escuro, width=1)
        draw.text((40, 495), "SUBTOTAL", font=f_normal, fill=cinza)
        bbox = draw.textbbox((0, 0), valor_txt, font=f_normal)
        w_txt = bbox[2] - bbox[0]
        draw.text((W - 40 - w_txt, 495), valor_txt, font=f_normal, fill=branco)

        box_y1, box_y2 = 570, 660
        draw.rectangle([(40, box_y1), (W - 40, box_y2)], fill=vermelho_escuro)
        draw.rectangle([(40, box_y1), (W - 40, box_y2)], outline=vermelho, width=2)
        draw.text((70, box_y1 + 30), "VALOR PAGO", font=f_medio, fill=branco)
        bbox = draw.textbbox((0, 0), valor_txt, font=f_grande)
        w_txt = bbox[2] - bbox[0]
        draw.text((W - 70 - w_txt, box_y1 + 22), valor_txt, font=f_grande, fill=branco)

        draw.text((40, 710), "DETALHES", font=f_medio, fill=cinza)
        draw.line([(40, 745), (W - 40, 745)], fill=cinza_escuro, width=1)

        draw.text((40, 765), "ID DO PEDIDO", font=f_pequena, fill=cinza)
        draw.text((40, 790), f"#{pedido['id']}", font=f_normal, fill=branco)

        draw.text((320, 765), "DATA", font=f_pequena, fill=cinza)
        data_str = pedido.get("pago_em", agora())[:16]
        draw.text((320, 790), data_str, font=f_normal, fill=branco)

        draw.text((620, 765), "ENTREGA", font=f_pequena, fill=cinza)
        draw.text((620, 790), "Enviada no PV", font=f_normal, fill=(87, 242, 135))

        draw.rectangle([(0, H - 80), (W, H)], fill=vermelho_escuro)
        draw.text((40, H - 55), "QZZ COMMUNITY #2K", font=f_medio, fill=branco)
        draw.text((W - 280, H - 50), "Obrigado pela compra 💚", font=f_pequena, fill=branco)

        draw.rectangle([(0, 0), (W - 1, H - 1)], outline=vermelho, width=3)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"[Recibo] erro: {e}")
        return None

# ═══════════════════════════════════════
#  SHARPIFY
# ═══════════════════════════════════════
async def sharpify_pagar(nome, descricao, valor):
    url = f"{SHARPIFY_BASE}/api/v1/gateway/payment/create-paymnet"
    headers = {
        "Content-Type": "application/json",
        "x-sharpify-client-id": SHARPIFY_ID,
        "x-sharpify-client-secret": SHARPIFY_SECRET
    }
    body = {
        "name": nome, "description": descricao,
        "amount": round(float(valor), 2), "gatewayMethod": "PIX"
    }
    if WEBHOOK_URL:
        body["webhook"] = {
            "callbackURL": WEBHOOK_URL,
            "headers": [{"key": "Authorization", "value": f"Bearer {SHARPIFY_WEBHOOK_SECRET}"}]
        }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=body, headers=headers) as r:
            txt = await r.text()
            try: data = json.loads(txt)
            except: data = {"raw": txt}
            print(f"[Sharpify] {r.status} -> {data}")
            if r.status >= 400: return None, data
            return data, None

# ═══════════════════════════════════════
#  WEBHOOK SHARPIFY
# ═══════════════════════════════════════
async def webhook_sharpify(request):
    try:
        auth = request.headers.get("Authorization", "")
        if SHARPIFY_WEBHOOK_SECRET and auth != f"Bearer {SHARPIFY_WEBHOOK_SECRET}":
            return web.Response(status=401, text="unauthorized")
        data = await request.json()
        event = data.get("event", {})
        wid = event.get("webhookId")
        evname = event.get("name")
        ctx = event.get("contextId")
        print(f"[Webhook] {evname} | {ctx} | {wid}")
        seen = get_seen()
        if wid in seen: return web.Response(text="dup")
        seen.append(wid)
        save("webhook_seen.json", seen[-500:])
        if evname == "PAYMENT_LINK_APPROVED":
            asyncio.create_task(entregar_pedido(ctx))
        return web.Response(text="ok")
    except Exception as e:
        print(f"[Webhook] erro: {e}")
        return web.Response(status=500, text="error")

# ═══════════════════════════════════════
#  ATUALIZAR CATÁLOGO
# ═══════════════════════════════════════
async def atualizar_catalogo(pid):
    try:
        postados = get_postados()
        for msg_id, dados in postados.items():
            if dados.get("produto_id") != pid:
                continue
            try:
                canal = bot.get_channel(int(dados["canal_id"]))
                if not canal:
                    continue
                msg = await canal.fetch_message(int(msg_id))
                nova_view = VerOpcoesView(pid)
                await msg.edit(view=nova_view)
            except Exception as ex:
                print(f"[Catálogo] erro msg {msg_id}: {type(ex).__name__}: {ex}")
    except Exception as e:
        print(f"[Catálogo] erro geral: {e}")

# ═══════════════════════════════════════
#  FECHAR THREAD EM BACKGROUND
# ═══════════════════════════════════════
async def fechar_thread_em(thread_id, segundos):
    await asyncio.sleep(segundos)
    try:
        thread = await bot.fetch_channel(int(thread_id))
        if thread and not thread.archived:
            await thread.edit(archived=True)
            print(f"[Thread] ✅ Arquivada: {thread_id}")
        else:
            print(f"[Thread] Já arquivada ou não encontrada: {thread_id}")
    except Exception as ex:
        print(f"[Thread] ❌ Erro ao arquivar {thread_id}: {type(ex).__name__}: {ex}")
        
# ═══════════════════════════════════════
#  ENTREGA AUTOMÁTICA
# ═══════════════════════════════════════
async def entregar_pedido(link_id):
    pedidos = get_pedidos()
    pedido = next((p for p in pedidos if p.get("payment_link_id") == link_id), None)
    if not pedido or pedido.get("status") == "entregue": return

    produtos = get_produtos()
    p = produtos.get(pedido["produto_id"])
    key = None
    cargo_id = None
    if p:
        v = p.get("variacoes", {}).get(pedido["variacao_id"])
        if v:
            if v.get("keys"):
                key = v["keys"].pop(0)
                set_produtos(produtos)
            cargo_id = v.get("cargo_id")

    pedido["status"] = "entregue" if key else "pago"
    pedido["key_entregue"] = key
    pedido["pago_em"] = agora()

    # ─── DM com key
    try:
        user = await bot.fetch_user(pedido["comprador_id"])
        if key:
            e = discord.Embed(
                title="🎉 Pagamento Confirmado",
                description=(
                    "**Sua compra foi aprovada com sucesso!**\n\n"
                    "╭─────────────────────────────╮\n"
                    "│  🔑 **SUA KEY ESTÁ ABAIXO**     │\n"
                    "╰─────────────────────────────╯"
                ),
                color=0x57F287,
                timestamp=datetime.now()
            )
            e.add_field(name="📦  Produto", value=f"```{pedido['produto_nome']}```", inline=False)
            e.add_field(name="🎁  Opção", value=f"```{pedido['variacao_nome']}```", inline=True)
            e.add_field(name="💰  Valor", value=f"`R$ {pedido['preco_final']:.2f}`", inline=True)
            e.add_field(name="🆔  Pedido", value=f"`#{pedido['id']}`", inline=True)
            e.add_field(name="\u200b", value="\u200b", inline=False)
            e.add_field(name="🔑  Key", value=f"```\n{key}\n```", inline=False)
            e.add_field(
                name="⚠️  Importante",
                value="> Guarde esta key em local seguro.\n> Não compartilhe com ninguém.",
                inline=False
            )
            e.set_footer(text="QZZ Vendas • Obrigado pela preferência 💚", icon_url=bot.user.display_avatar.url)
            await user.send(embed=e)
        else:
            e = discord.Embed(
                title="✅ Pagamento Confirmado",
                description=f"Seu pedido **#{pedido['id']}** foi aprovado.\nUm membro da equipe vai te entregar em breve.",
                color=0x57F287, timestamp=datetime.now()
            )
            await user.send(embed=e)
    except Exception as e:
        print(f"[DM] erro: {e}")

    # ─── Cargo automático
    if cargo_id:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            try:
                member = await guild.fetch_member(pedido["comprador_id"])
                cargo = guild.get_role(int(cargo_id))
                if member and cargo:
                    await member.add_roles(cargo, reason=f"Compra #{pedido['id']}")
                    pedido["cargo_dado"] = cargo.name
            except Exception as e:
                print(f"[Cargo] erro: {e}")

    set_pedidos(pedidos)

    # ─── RECIBO no canal de entregas
    if CANAL_ENTREGAS:
        ch = bot.get_channel(CANAL_ENTREGAS)
        if ch:
            try:
                buf = await gerar_recibo_imagem(pedido)
                if buf:
                    file = discord.File(buf, filename=f"recibo_{pedido['id']}.png")
                    e = discord.Embed(
                        title="✅ Nova Compra Realizada!",
                        description=(
                            f"👤  Cliente: <@{pedido['comprador_id']}>\n"
                            f"📩  Key entregue no PV automaticamente."
                        ),
                        color=0x57F287, timestamp=datetime.now()
                    )
                    e.set_image(url=f"attachment://recibo_{pedido['id']}.png")
                    e.set_footer(text=f"Pedido #{pedido['id']} • Obrigado pela preferência 💚", icon_url=bot.user.display_avatar.url)
                    await ch.send(embed=e, file=file)
            except Exception as e:
                print(f"[Entregas] erro: {e}")

    # ─── Log staff
    if CANAL_LOGS:
        ch = bot.get_channel(CANAL_LOGS)
        if ch:
            e = discord.Embed(
                title="💸 Nova Venda Aprovada",
                description="╭─────────────────────────────╮\n│  📊  **DETALHES DA VENDA**       │\n╰─────────────────────────────╯",
                color=0x57F287, timestamp=datetime.now()
            )
            e.add_field(name="🆔  Pedido", value=f"`#{pedido['id']}`", inline=True)
            e.add_field(name="👤  Cliente", value=f"<@{pedido['comprador_id']}>", inline=True)
            e.add_field(name="💰  Valor", value=f"`R$ {pedido['preco_final']:.2f}`", inline=True)
            e.add_field(name="📦  Produto", value=pedido["produto_nome"], inline=True)
            e.add_field(name="🎁  Opção", value=pedido["variacao_nome"], inline=True)
            e.add_field(name="🎭  Cargo dado", value=pedido.get("cargo_dado", "—"), inline=True)
            e.add_field(name="🔑  Key Entregue", value=f"||`{key}`||" if key else "❌ Sem estoque", inline=False)
            e.set_footer(text="QZZ Vendas • Log automático", icon_url=bot.user.display_avatar.url)
            await ch.send(embed=e)

    await atualizar_catalogo(pedido["produto_id"])

    # ─── Fecha thread (em background)
    if pedido.get("thread_id"):
        try:
            thread = bot.get_channel(int(pedido["thread_id"]))
            if thread:
                e = discord.Embed(
                    title="✅ Pagamento Aprovado!",
                    description=(
                        "╭─────────────────────────────╮\n"
                        "│  🎉  **COMPRA CONFIRMADA**      │\n"
                        "╰─────────────────────────────╯\n\n"
                        "📩  **A key foi enviada no seu PV.**\n\n"
                        "**Esta thread será fechada em 10 segundos...**"
                    ),
                    color=0x57F287, timestamp=datetime.now()
                )
                await thread.send(embed=e)
                asyncio.create_task(fechar_thread_em(pedido["thread_id"], 10))
        except Exception as e:
            print(f"[Thread] Erro ao notificar: {type(e).__name__}: {e}")

# ═══════════════════════════════════════
#  CANCELAR PEDIDO
# ═══════════════════════════════════════
async def cancelar_pedido(pedido_id, cancelado_por):
    pedidos = get_pedidos()
    pedido = next((p for p in pedidos if p["id"] == pedido_id), None)
    if not pedido:
        return False, "Pedido não encontrado."
    if pedido["status"] in ("entregue", "pago"):
        return False, "Este pedido já foi pago e não pode ser cancelado."
    if pedido["status"] == "cancelado":
        return False, "Este pedido já foi cancelado."

    pedido["status"] = "cancelado"
    pedido["cancelado_em"] = agora()
    pedido["cancelado_por"] = str(cancelado_por)
    set_pedidos(pedidos)

    if pedido.get("thread_id"):
        try:
            thread = bot.get_channel(int(pedido["thread_id"]))
            if thread:
                e = discord.Embed(
                    title="❌ Pedido Cancelado",
                    description="O pedido foi cancelado.\n\n**Thread fechada em 10 segundos...**",
                    color=0xED4245, timestamp=datetime.now()
                )
                await thread.send(embed=e)
                asyncio.create_task(fechar_thread_em(pedido["thread_id"], 10))
        except Exception as e:
            print(f"[Cancelar/Thread] erro: {e}")

    if CANAL_LOGS:
        ch = bot.get_channel(CANAL_LOGS)
        if ch:
            e = discord.Embed(title="❌ Pedido Cancelado", color=0xED4245, timestamp=datetime.now())
            e.add_field(name="🆔  Pedido", value=f"`#{pedido_id}`", inline=True)
            e.add_field(name="👤  Cliente", value=f"<@{pedido['comprador_id']}>", inline=True)
            e.add_field(name="❌  Cancelado por", value=str(cancelado_por), inline=True)
            await ch.send(embed=e)

    return True, "Pedido cancelado com sucesso."

# ═══════════════════════════════════════
#  WEB SERVER
# ═══════════════════════════════════════
async def health(request): return web.Response(text="OK")

async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_post("/webhook/sharpify", webhook_sharpify)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Web server porta {port}")

# ═══════════════════════════════════════
#  EMBEDS
# ═══════════════════════════════════════
def embed_painel_admin(user):
    cfg = get_config()
    prods = get_produtos()
    total_keys = 0
    for p in prods.values():
        for v in p.get("variacoes", {}).values():
            total_keys += len(v.get("keys", []))
    e = discord.Embed(
        title="🛠️  Painel de Administração",
        description=(
            f"Olá, **{user.display_name}**!\n\n"
            "╭─────────────────────────────╮\n"
            "│  🏪  Gerencie sua loja abaixo   │\n"
            "╰─────────────────────────────╯"
        ),
        color=cfg.get("cor_principal", 0x5865F2),
        timestamp=datetime.now()
    )
    e.add_field(name="📦  Produtos", value=f"`{len(prods)}`", inline=True)
    e.add_field(name="🔑  Keys", value=f"`{total_keys}`", inline=True)
    e.add_field(name="🏪  Loja", value=f"`{cfg.get('nome_loja', 'QZZ Vendas')}`", inline=True)
    e.set_footer(text="Sharpify + Supabase", icon_url=bot.user.display_avatar.url)
    return e

def montar_embed_catalogo(titulo, nome_sub, bullets, recebe, produto):
    linhas_nome = [l.strip() for l in nome_sub.split("\n") if l.strip()]
    nome = linhas_nome[0] if len(linhas_nome) > 0 else produto.get("nome", "")
    subtitulo = linhas_nome[1] if len(linhas_nome) > 1 else ""

    linhas_b = [l.strip() for l in bullets.split("\n") if l.strip()]
    bullets_txt = "\n".join(linhas_b) if linhas_b else "—"
    linhas_r = [l.strip() for l in recebe.split("\n") if l.strip()]
    recebe_txt = "\n".join(linhas_r) if linhas_r else "—"

    desc = f"🔴 **{titulo}**\n"
    desc += "✅ **Entrega Automática!**\n\n"
    desc += f"**{nome}**\n"
    if subtitulo:
        desc += f"📦 *{subtitulo}*\n"
    desc += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    desc += bullets_txt
    desc += "\n\n**📦 VOCÊ RECEBE**\n"
    desc += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    desc += recebe_txt

    e = discord.Embed(description=desc, color=0xED4245)
    img = produto.get("imagem")
    if img and url_imagem_valida(img):
        try: e.set_image(url=img)
        except: pass
    e.set_footer(text=f"🛒  {produto['nome']}  •  Escolha uma opção no menu abaixo", icon_url=bot.user.display_avatar.url)
    e.timestamp = datetime.now()
    return e

# ═══════════════════════════════════════
#  MODAIS
# ═══════════════════════════════════════
class CriarProdutoModal(discord.ui.Modal, title="➕ Criar Produto"):
    nome = discord.ui.TextInput(label="Nome do produto", required=True, max_length=100)
    descricao = discord.ui.TextInput(label="Descrição curta", required=True, style=discord.TextStyle.paragraph, max_length=500)
    imagem = discord.ui.TextInput(label="URL da imagem (opcional)", required=False, max_length=500)
    categoria = discord.ui.TextInput(label="Categoria (apps/vpn/jogos/gift)", required=True, max_length=20)

    async def on_submit(self, i):
        if not is_staff(i.user):
            await i.response.send_message("❌ Sem permissão.", ephemeral=True); return
        cat = self.categoria.value.lower().strip()
        if cat not in get_catalogos():
            await i.response.send_message(f"❌ Categoria inválida. Use: `{'`, `'.join(get_catalogos().keys())}`", ephemeral=True); return
        prods = get_produtos()
        pid = novo_id()
        prods[pid] = {
            "id": pid, "nome": self.nome.value, "descricao": self.descricao.value,
            "imagem": self.imagem.value or None, "categoria": cat,
            "variacoes": {}, "ativo": True, "criado_em": agora(),
            "catalogo_salvo": None
        }
        set_produtos(prods)
        await i.response.send_message(f"✅ Produto **{self.nome.value}** criado! ID: `{pid}`", ephemeral=True)

class EditarProdutoModal(discord.ui.Modal, title="✏️ Editar Produto"):
    nome = discord.ui.TextInput(label="Nome (vazio = manter)", required=False, max_length=100)
    descricao = discord.ui.TextInput(label="Descrição (vazio = manter)", required=False, style=discord.TextStyle.paragraph, max_length=500)
    imagem = discord.ui.TextInput(label="URL da imagem (vazio = manter)", required=False, max_length=500)

    def __init__(self, pid):
        super().__init__()
        self.pid = pid

    async def on_submit(self, i):
        prods = get_produtos()
        if self.pid not in prods:
            await i.response.send_message("❌ Produto não encontrado.", ephemeral=True); return
        p = prods[self.pid]
        if self.nome.value: p["nome"] = self.nome.value
        if self.descricao.value: p["descricao"] = self.descricao.value
        if self.imagem.value: p["imagem"] = self.imagem.value
        set_produtos(prods)
        await i.response.send_message("✅ Produto atualizado!", ephemeral=True)
        await atualizar_catalogo(self.pid)

class CriarVariacaoModal(discord.ui.Modal, title="➕ Criar Variação"):
    nome = discord.ui.TextInput(label="Nome da variação", required=True, max_length=100)
    preco = discord.ui.TextInput(label="Preço (ex: 13.99)", required=True, max_length=10)

    def __init__(self, pid):
        super().__init__()
        self.pid = pid

    async def on_submit(self, i):
        try: preco = float(self.preco.value.replace(",", "."))
        except:
            await i.response.send_message("❌ Preço inválido.", ephemeral=True); return
        prods = get_produtos()
        if self.pid not in prods:
            await i.response.send_message("❌ Produto não encontrado.", ephemeral=True); return
        vid = novo_id()
        prods[self.pid]["variacoes"][vid] = {
            "id": vid, "nome": self.nome.value, "preco": preco, "keys": [], "cargo_id": None
        }
        set_produtos(prods)
        await i.response.send_message(f"✅ Variação **{self.nome.value}** criada!", ephemeral=True)

class AddKeysModal(discord.ui.Modal, title="➕ Adicionar Keys"):
    keys = discord.ui.TextInput(label="Cole as keys (uma por linha)", style=discord.TextStyle.paragraph, required=True, max_length=4000)

    def __init__(self, pid, vid):
        super().__init__()
        self.pid = pid
        self.vid = vid

    async def on_submit(self, i):
        prods = get_produtos()
        v = prods.get(self.pid, {}).get("variacoes", {}).get(self.vid)
        if not v:
            await i.response.send_message("❌ Variação não encontrada.", ephemeral=True); return
        novas = [k.strip() for k in self.keys.value.split("\n") if k.strip()]
        v.setdefault("keys", []).extend(novas)
        set_produtos(prods)
        await i.response.send_message(f"✅ **{len(novas)}** keys adicionadas!\nTotal: `{len(v['keys'])}`", ephemeral=True)
        await atualizar_catalogo(self.pid)

class DeletarKeysModal(discord.ui.Modal, title="🗑️ Deletar Keys"):
    keys = discord.ui.TextInput(label="Cole as keys a deletar (uma por linha)", style=discord.TextStyle.paragraph, required=True, max_length=4000)

    def __init__(self, pid, vid):
        super().__init__()
        self.pid = pid
        self.vid = vid

    async def on_submit(self, i):
        prods = get_produtos()
        v = prods.get(self.pid, {}).get("variacoes", {}).get(self.vid)
        if not v:
            await i.response.send_message("❌ Variação não encontrada.", ephemeral=True); return
        deletar = set(k.strip() for k in self.keys.value.split("\n") if k.strip())
        antes = len(v.get("keys", []))
        v["keys"] = [k for k in v.get("keys", []) if k not in deletar]
        depois = len(v["keys"])
        set_produtos(prods)
        await i.response.send_message(f"🗑️ **{antes - depois}** keys deletadas.\nRestam: `{depois}`", ephemeral=True)
        await atualizar_catalogo(self.pid)

class PostarCatalogoModal(discord.ui.Modal, title="📢 Conteúdo do Catálogo"):
    titulo = discord.ui.TextInput(
        label="Título (linha vermelha)",
        placeholder="Ex: AUXILIO EXTERNAL - ANDROID",
        required=True, max_length=100
    )
    nome_sub = discord.ui.TextInput(
        label="Nome + Subtítulo (2 linhas)",
        placeholder="PRECISION EXTERNAL - ANDROID E IOS\nPRECISION MOBILE PREMIUM",
        style=discord.TextStyle.paragraph,
        required=True, max_length=250
    )
    bullets = discord.ui.TextInput(
        label="✅ Benefícios (1 por linha)",
        placeholder="✅ Compatível com Android\n🔒 APK + Arquivo Incluso\n⚡ Instalação rápida",
        style=discord.TextStyle.paragraph,
        required=True, max_length=1500
    )
    recebe = discord.ui.TextInput(
        label="📦 O que recebe (1 por linha)",
        placeholder="✅ Precision External Mobile\n✅ APK + Arquivo Injetável\n✅ Tutorial de instalação",
        style=discord.TextStyle.paragraph,
        required=True, max_length=1000
    )

    def __init__(self, pid, canal_id, salvar=True):
        super().__init__()
        self.pid = pid
        self.canal_id = canal_id
        self.salvar = salvar

    async def on_submit(self, i):
        if not is_staff(i.user):
            await i.response.send_message("❌ Sem permissão.", ephemeral=True); return

        prods = get_produtos()
        p = prods.get(self.pid)
        if not p:
            await i.response.send_message("❌ Produto não encontrado.", ephemeral=True); return

        canal = i.guild.get_channel(int(self.canal_id))
        if not canal:
            await i.response.send_message("❌ Canal não encontrado.", ephemeral=True); return

        if self.salvar:
            p["catalogo_salvo"] = {
                "titulo": self.titulo.value,
                "nome_sub": self.nome_sub.value,
                "bullets": self.bullets.value,
                "recebe": self.recebe.value,
                "atualizado_em": agora()
            }
            set_produtos(prods)

        e = montar_embed_catalogo(
            self.titulo.value,
            self.nome_sub.value,
            self.bullets.value,
            self.recebe.value,
            p
        )
        view = VerOpcoesView(self.pid)
        msg = await canal.send(embed=e, view=view)

        postados = get_postados()
        postados[str(msg.id)] = {"produto_id": self.pid, "canal_id": str(canal.id)}
        set_postados(postados)
        await i.response.send_message(f"✅ Catálogo postado em {canal.mention}!", ephemeral=True)
        
# ═══════════════════════════════════════
#  VIEW: CATÁLOGO
# ═══════════════════════════════════════
class VerOpcoesView(discord.ui.View):
    def __init__(self, pid):
        super().__init__(timeout=None)
        self.pid = pid
        self.add_item(VerOpcoesSelect(pid))

class VerOpcoesSelect(discord.ui.Select):
    def __init__(self, pid):
        self.pid = pid
        prods = get_produtos()
        p = prods.get(pid)
        opts = []
        if p:
            for vid, v in list(p.get("variacoes", {}).items())[:25]:
                estoque = len(v.get("keys", []))
                emoji = "🟢" if estoque > 5 else ("🟡" if estoque > 0 else "🔴")
                opts.append(discord.SelectOption(
                    label=v["nome"][:100],
                    description=f"R$ {v['preco']:.2f} • {estoque} em estoque",
                    value=vid, emoji=emoji
                ))
        if not opts:
            opts = [discord.SelectOption(label="Sem opções", value="none")]
        super().__init__(placeholder="🎁  Selecione uma opção para comprar...", options=opts, min_values=1, max_values=1)

    async def callback(self, i):
        if self.values[0] == "none":
            await i.response.send_message("❌ Nenhuma opção.", ephemeral=True); return
        prods = get_produtos()
        p = prods.get(self.pid)
        if not p:
            await i.response.send_message("❌ Produto não encontrado.", ephemeral=True); return
        v = p.get("variacoes", {}).get(self.values[0])
        if not v or not v.get("keys"):
            await i.response.send_message("❌ Esgotada! Escolha outra.", ephemeral=True); return
        await abrir_thread_compra(i, self.pid, self.values[0])

# ═══════════════════════════════════════
#  THREAD DE COMPRA
# ═══════════════════════════════════════
async def abrir_thread_compra(i, pid, vid):
    prods = get_produtos()
    p = prods.get(pid)
    v = p.get("variacoes", {}).get(vid) if p else None
    if not p or not v:
        await i.response.send_message("❌ Erro.", ephemeral=True); return

    canal = i.channel
    nome_thread = f"compra-{i.user.name}-{novo_id()[:4]}"
    try:
        thread = await canal.create_thread(name=nome_thread, type=discord.ChannelType.private_thread, invitable=False, auto_archive_duration=60)
    except Exception as e:
        await i.response.send_message(f"❌ Erro thread: {e}", ephemeral=True); return

    try: await thread.add_user(i.user)
    except: pass
    for cid in CARGOS_STAFF:
        try:
            cargo = i.guild.get_role(cid)
            if cargo:
                for m in cargo.members[:5]:
                    try: await thread.add_user(m)
                    except: pass
        except: pass

    pedidos = get_pedidos()
    num = (max([x["id"] for x in pedidos]) + 1) if pedidos else 1
    pedido = {
        "id": num, "comprador_id": i.user.id, "comprador_nome": str(i.user),
        "produto_id": pid, "produto_nome": p["nome"], "variacao_id": vid,
        "variacao_nome": v["nome"], "preco_final": round(float(v["preco"]), 2),
        "thread_id": thread.id, "status": "aguardando_confirmacao", "criado_em": agora()
    }
    pedidos.append(pedido)
    set_pedidos(pedidos)

    e = discord.Embed(
        title="🛒  Detalhes do Pedido",
        description=(
            "Confira as informações abaixo:\n\n"
            "╭─────────────────────────────╮\n"
            f"│  👤  Cliente: {i.user.mention}\n"
            f"│  🆔  Pedido: `#{num}`\n"
            "╰─────────────────────────────╯"
        ),
        color=0x5865F2, timestamp=datetime.now()
    )
    e.add_field(name="📦  Produto", value=f"**{p['nome']}**", inline=False)
    e.add_field(name="🎁  Opção", value=f"`{v['nome']}`", inline=True)
    e.add_field(name="💰  Preço", value=f"`R$ {v['preco']:.2f}`", inline=True)
    e.add_field(name="\u200b", value="\u200b", inline=True)
    e.add_field(name="ℹ️  Próximo passo", value="Clique no botão abaixo para prosseguir.", inline=False)
    if p.get("imagem"): e.set_thumbnail(url=p["imagem"])
    e.set_footer(text="QZZ Vendas • Pagamento seguro via Pix", icon_url=bot.user.display_avatar.url)

    await thread.send(content=i.user.mention, embed=e, view=ProsseguirView(pedido["id"]))
    await i.response.send_message(f"✅ Thread criada: {thread.mention}", ephemeral=True)

# ═══════════════════════════════════════
#  VIEWS DA THREAD
# ═══════════════════════════════════════
class ProsseguirView(discord.ui.View):
    def __init__(self, pedido_id):
        super().__init__(timeout=None)
        self.pedido_id = pedido_id

    @discord.ui.button(label="Prosseguir para pagamento", emoji="➡️", style=discord.ButtonStyle.success)
    async def prosseguir(self, i, b):
        import sys, traceback
        try:
            print(f"🔥 [PROSSEGUIR] Iniciou pedido_id={self.pedido_id}", file=sys.stderr, flush=True)

            pedidos = get_pedidos()
            pedido = next((p for p in pedidos if p["id"] == self.pedido_id), None)
            if not pedido:
                await i.response.send_message("❌ Pedido não encontrado.", ephemeral=True); return
            if i.user.id != pedido["comprador_id"]:
                await i.response.send_message("❌ Só o comprador.", ephemeral=True); return

            print(f"🔥 [PROSSEGUIR] Pedido OK #{pedido['id']}", file=sys.stderr, flush=True)

            b.disabled = True
            await i.response.edit_message(view=self)
            print(f"🔥 [PROSSEGUIR] Botão desabilitado OK", file=sys.stderr, flush=True)

            e = discord.Embed(
                title="💳  Método de Pagamento",
                description=(
                    "Escolha como deseja pagar:\n\n"
                    "╭─────────────────────────────╮\n"
                    "│  💠  **Pix** — Aprovação na hora   │\n"
                    "│  ⚡  Entrega automática da key      │\n"
                    "╰─────────────────────────────╯"
                ),
                color=0xFEE75C
            )
            e.set_footer(text="Selecione abaixo", icon_url=bot.user.display_avatar.url)
            print(f"🔥 [PROSSEGUIR] Embed montado OK", file=sys.stderr, flush=True)

            view = MetodoPagamentoView(self.pedido_id)
            print(f"🔥 [PROSSEGUIR] View criada OK", file=sys.stderr, flush=True)

            await i.followup.send(embed=e, view=view)
            print(f"🔥 [PROSSEGUIR] ✅ Mensagem enviada com sucesso!", file=sys.stderr, flush=True)

        except Exception as ex:
            print(f"🔥 [PROSSEGUIR] ❌ ERRO: {type(ex).__name__}: {ex}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            try:
                await i.followup.send(f"❌ Erro: `{type(ex).__name__}`\n```{str(ex)[:300]}```", ephemeral=True)
            except: pass

class MetodoPagamentoView(discord.ui.View):
    def __init__(self, pedido_id):
        super().__init__(timeout=600)
        self.pedido_id = pedido_id

    @discord.ui.button(label="Pix", emoji="💳", style=discord.ButtonStyle.primary)
    async def pix(self, i, b):
        import sys, traceback
        try:
            print(f"🔥 [PIX] Iniciou pedido_id={self.pedido_id}", file=sys.stderr, flush=True)

            pedidos = get_pedidos()
            pedido = next((p for p in pedidos if p["id"] == self.pedido_id), None)
            if not pedido:
                await i.response.send_message("❌ Não encontrado.", ephemeral=True); return
            if i.user.id != pedido["comprador_id"]:
                await i.response.send_message("❌ Só o comprador.", ephemeral=True); return

            print(f"🔥 [PIX] Pedido OK", file=sys.stderr, flush=True)

            b.disabled = True
            try: await i.response.edit_message(view=self)
            except Exception as ex: print(f"🔥 [PIX] edit_message erro: {ex}", file=sys.stderr, flush=True)
            try: await i.followup.send("💳  Gerando seu Pix... ⏳", ephemeral=True)
            except Exception as ex: print(f"🔥 [PIX] followup erro: {ex}", file=sys.stderr, flush=True)

            print(f"🔥 [PIX] Chamando sharpify_pagar...", file=sys.stderr, flush=True)

            resp, err = await sharpify_pagar(
                f"{pedido['produto_nome']} - {pedido['variacao_nome']}",
                f"Pedido #{pedido['id']}",
                pedido["preco_final"]
            )

            if err or not resp:
                await i.followup.send(f"❌ Erro ao gerar Pix.\n```{str(err)[:300]}```")
                return

            print(f"🔥 [PIX] Sharpify respondeu OK", file=sys.stderr, flush=True)

            d = resp.get("data", resp)
            payment = d.get("payment") or {}
            gdata = (payment.get("gateway") or {}).get("data") or {}
            qr = gdata.get("qrCode") or ""
            copia = gdata.get("code") or ""

            pedido["payment_link_id"] = d.get("id")
            pedido["status"] = "aguardando_pagamento"
            set_pedidos(pedidos)

            e = discord.Embed(
                title="💳  Pagamento via Pix",
                description=(
                    "**Escaneie o QR Code** com seu banco ou app.\n"
                    "Assim que o pagamento for confirmado, a key chega automaticamente. ⚡\n\n"
                    "╭─────────────────────────────╮\n"
                    f"│  🆔  Pedido: `#{pedido['id']}`\n"
                    f"│  💰  Valor: `R$ {pedido['preco_final']:.2f}`\n"
                    "╰─────────────────────────────╯"
                ),
                color=0x57F287, timestamp=datetime.now()
            )
            e.add_field(name="📦  Produto", value=f"**{pedido['produto_nome']}**\n└ {pedido['variacao_nome']}", inline=False)
            e.set_footer(text="Aguardando pagamento... ⏳", icon_url=bot.user.display_avatar.url)

            enviado = False
            if qr and qr.startswith("data:image"):
                try:
                    header, b64 = qr.split(",", 1)
                    img_bytes = base64.b64decode(b64)
                    file = discord.File(io.BytesIO(img_bytes), filename="qrcode.png")
                    e.set_image(url="attachment://qrcode.png")
                    await i.followup.send(embed=e, file=file, view=PixAcoesView(pedido["id"], copia))
                    enviado = True
                    print(f"🔥 [PIX] QR enviado", file=sys.stderr, flush=True)
                except Exception as ex: print(f"🔥 [QR] erro: {ex}", file=sys.stderr, flush=True)
            if not enviado:
                await i.followup.send(embed=e, view=PixAcoesView(pedido["id"], copia))
                print(f"🔥 [PIX] Embed enviado sem QR", file=sys.stderr, flush=True)

            if copia:
                try:
                    e_pv = discord.Embed(
                        title="📋  Pix Copia e Cola",
                        description=(
                            f"**Pedido #{pedido['id']}**\n\n"
                            f"```\n{copia}\n```\n"
                            "_Copie o código acima e cole no seu banco._"
                        ),
                        color=0x57F287
                    )
                    await i.user.send(embed=e_pv)
                    print(f"🔥 [PIX] ✅ Copia e cola enviado no PV", file=sys.stderr, flush=True)
                except Exception as ex_pv: print(f"🔥 [PV] erro: {ex_pv}", file=sys.stderr, flush=True)

            print(f"🔥 [PIX] ✅✅ CONCLUÍDO COM SUCESSO!", file=sys.stderr, flush=True)

        except Exception as ex:
            print(f"🔥 [PIX] ❌ ERRO: {type(ex).__name__}: {ex}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            try:
                await i.followup.send(f"❌ Erro: `{type(ex).__name__}`\n```{str(ex)[:300]}```", ephemeral=True)
            except: pass

class PixAcoesView(discord.ui.View):
    def __init__(self, pedido_id, copia):
        super().__init__(timeout=None)
        self.pedido_id = pedido_id
        self.copia = copia

    @discord.ui.button(label="Ver código Pix", emoji="📋", style=discord.ButtonStyle.primary)
    async def ver_codigo(self, i, b):
        pedidos = get_pedidos()
        pedido = next((p for p in pedidos if p["id"] == self.pedido_id), None)
        if not pedido:
            await i.response.send_message("❌ Pedido não encontrado.", ephemeral=True); return
        if i.user.id != pedido["comprador_id"]:
            await i.response.send_message("❌ Só o comprador.", ephemeral=True); return
        e = discord.Embed(
            title="📋  Pix Copia e Cola",
            description=f"**Pedido #{self.pedido_id}**\n\n```\n{self.copia}\n```\n\n👆 **Selecione e copie.**",
            color=0x57F287
        )
        e.set_footer(text="Aguardando confirmação...", icon_url=bot.user.display_avatar.url)
        await i.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="Cancelar Pagamento", emoji="❌", style=discord.ButtonStyle.danger)
    async def cancelar(self, i, b):
        pedidos = get_pedidos()
        pedido = next((p for p in pedidos if p["id"] == self.pedido_id), None)
        if not pedido:
            await i.response.send_message("❌ Pedido não encontrado.", ephemeral=True); return
        if i.user.id != pedido["comprador_id"]:
            await i.response.send_message("❌ Só o comprador pode cancelar.", ephemeral=True); return
        if pedido["status"] in ("entregue", "pago", "cancelado"):
            await i.response.send_message("⚠️ Este pedido não pode mais ser cancelado.", ephemeral=True); return
        e = discord.Embed(
            title="⚠️  Confirmar Cancelamento",
            description=(
                f"**Tem certeza que deseja cancelar?**\n\n"
                f"╭─────────────────────────────╮\n"
                f"│  🆔  Pedido: `#{self.pedido_id}`\n"
                f"│  📦  {pedido['produto_nome']}\n"
                f"│  🎁  {pedido['variacao_nome']}\n"
                f"│  💰  `R$ {pedido['preco_final']:.2f}`\n"
                f"╰─────────────────────────────╯"
            ),
            color=0xED4245
        )
        await i.response.send_message(embed=e, view=ConfirmarCancelarView(self.pedido_id), ephemeral=True)

class ConfirmarCancelarView(discord.ui.View):
    def __init__(self, pedido_id):
        super().__init__(timeout=120)
        self.pedido_id = pedido_id

    @discord.ui.button(label="Sim, cancelar", emoji="✅", style=discord.ButtonStyle.danger)
    async def sim(self, i, b):
        pedidos = get_pedidos()
        pedido = next((p for p in pedidos if p["id"] == self.pedido_id), None)
        if not pedido:
            await i.response.send_message("❌ Pedido não encontrado.", ephemeral=True); return
        if i.user.id != pedido["comprador_id"]:
            await i.response.send_message("❌ Só o comprador.", ephemeral=True); return
        b.disabled = True
        try: await i.response.edit_message(view=self)
        except: pass
        sucesso, msg = await cancelar_pedido(self.pedido_id, i.user)
        if sucesso:
            e = discord.Embed(title="❌  Pedido Cancelado", description="Seu pedido foi cancelado.\n\nSe mudar de ideia, pode comprar novamente! 💚", color=0xED4245)
            await i.followup.send(embed=e, ephemeral=True)
        else:
            await i.followup.send(f"❌ {msg}", ephemeral=True)

    @discord.ui.button(label="Não, voltar", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def nao(self, i, b):
        await i.response.edit_message(content="✅ Ação cancelada. Você pode continuar o pagamento.", embed=None, view=None)

# ═══════════════════════════════════════
#  MENU DE POSTAR CATÁLOGO
# ═══════════════════════════════════════
class EscolherModoCatalogoView(discord.ui.View):
    def __init__(self, pid, canal_id, salvo):
        super().__init__(timeout=180)
        self.pid = pid
        self.canal_id = canal_id
        self.salvo = salvo

    @discord.ui.button(label="Usar o salvo", emoji="📋", style=discord.ButtonStyle.success)
    async def usar_salvo(self, i, b):
        try:
            prods = get_produtos()
            p = prods.get(self.pid)
            canal = i.guild.get_channel(int(self.canal_id))
            if not canal:
                await i.response.send_message("❌ Canal não encontrado.", ephemeral=True); return

            e = montar_embed_catalogo(
                self.salvo.get("titulo", ""),
                self.salvo.get("nome_sub", p.get("nome", "")),
                self.salvo.get("bullets", ""),
                self.salvo.get("recebe", ""),
                p
            )
            msg = await canal.send(embed=e, view=VerOpcoesView(self.pid))
            postados = get_postados()
            postados[str(msg.id)] = {"produto_id": self.pid, "canal_id": str(canal.id)}
            set_postados(postados)
            await i.response.edit_message(content=f"✅ Catálogo postado em {canal.mention}!", embed=None, view=None)
        except Exception as ex:
            await i.response.send_message(f"❌ Erro: {ex}", ephemeral=True)

    @discord.ui.button(label="Editar antes de postar", emoji="✏️", style=discord.ButtonStyle.primary)
    async def editar(self, i, b):
        modal = PostarCatalogoModal(self.pid, self.canal_id, salvar=True)
        modal.titulo.default = self.salvo.get("titulo", "")
        modal.nome_sub.default = self.salvo.get("nome_sub", "")
        modal.bullets.default = self.salvo.get("bullets", "")
        modal.recebe.default = self.salvo.get("recebe", "")
        await i.response.send_modal(modal)

    @discord.ui.button(label="Criar novo", emoji="🆕", style=discord.ButtonStyle.secondary)
    async def novo(self, i, b):
        await i.response.send_modal(PostarCatalogoModal(self.pid, self.canal_id, salvar=True))

# ═══════════════════════════════════════
#  PAINEL ADMIN
# ═══════════════════════════════════════
class PainelAdminView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Criar Produto", emoji="➕", style=discord.ButtonStyle.success, custom_id="adm_criar")
    async def criar(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌ Sem permissão.", ephemeral=True); return
        await i.response.send_modal(CriarProdutoModal())

    @discord.ui.button(label="Gerenciar Produtos", emoji="📦", style=discord.ButtonStyle.primary, custom_id="adm_prods")
    async def prods(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌ Sem permissão.", ephemeral=True); return
        prods = get_produtos()
        if not prods:
            await i.response.send_message("❌ Nenhum produto.", ephemeral=True); return
        opts = [discord.SelectOption(label=p["nome"][:100], description=f"{len(p.get('variacoes', {}))} opções", value=pid) for pid, p in list(prods.items())[:25]]
        await i.response.send_message("📦 Selecione:", view=SelProdutoAdmin(opts), ephemeral=True)

    @discord.ui.button(label="Postar Catálogo", emoji="📢", style=discord.ButtonStyle.secondary, custom_id="adm_postar")
    async def postar(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌ Sem permissão.", ephemeral=True); return
        prods = get_produtos()
        if not prods:
            await i.response.send_message("❌ Nenhum produto.", ephemeral=True); return
        opts = [discord.SelectOption(label=p["nome"][:100], description="Postar catálogo", value=pid) for pid, p in list(prods.items())[:25]]
        await i.response.send_message("📢 Escolha o produto:", view=SelProdutoPostar(opts), ephemeral=True)

    @discord.ui.button(label="Estatísticas", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="adm_stats")
    async def stats(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌ Sem permissão.", ephemeral=True); return
        pedidos = get_pedidos()
        pagos = [p for p in pedidos if p["status"] == "entregue"]
        pend = [p for p in pedidos if p["status"] in ("pendente", "aguardando_pagamento", "aguardando_confirmacao")]
        fat = sum(p["preco_final"] for p in pagos)
        e = discord.Embed(title="📊  Estatísticas da Loja", description="╭─────────────────────────────╮\n│  📈  **VISÃO GERAL**            │\n╰─────────────────────────────╯", color=0x5865F2, timestamp=datetime.now())
        e.add_field(name="🛒  Total de Pedidos", value=f"`{len(pedidos)}`", inline=True)
        e.add_field(name="✅  Entregues", value=f"`{len(pagos)}`", inline=True)
        e.add_field(name="⏳  Em Andamento", value=f"`{len(pend)}`", inline=True)
        e.add_field(name="💰  Faturamento", value=f"`R$ {fat:.2f}`", inline=False)
        e.set_footer(text="QZZ Vendas", icon_url=bot.user.display_avatar.url)
        await i.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="Resumo Estoque", emoji="🔑", style=discord.ButtonStyle.secondary, custom_id="adm_est")
    async def estoque(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌ Sem permissão.", ephemeral=True); return
        prods = get_produtos()
        if not prods:
            await i.response.send_message("❌ Nenhum produto.", ephemeral=True); return
        e = discord.Embed(title="🔑  Resumo de Estoque", description="╭─────────────────────────────╮\n│  📦  **ESTOQUE POR PRODUTO**    │\n╰─────────────────────────────╯", color=0x5865F2, timestamp=datetime.now())
        total = 0
        for p in prods.values():
            linhas = []
            for v in p.get("variacoes", {}).values():
                qtd = len(v.get("keys", []))
                total += qtd
                emoji = "🟢" if qtd > 5 else ("🟡" if qtd > 0 else "🔴")
                linhas.append(f"{emoji}  {v['nome']} — `{qtd}`")
            if linhas: e.add_field(name=f"📦  {p['nome']}", value="\n".join(linhas), inline=False)
        e.set_footer(text=f"Total: {total} keys", icon_url=bot.user.display_avatar.url)
        await i.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="Atualizar Catálogos", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="adm_atualizar")
    async def atualizar(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌ Sem permissão.", ephemeral=True); return
        prods = get_produtos()
        if not prods:
            await i.response.send_message("❌ Nenhum produto.", ephemeral=True); return
        await i.response.defer(ephemeral=True, thinking=True)
        total = 0
        for pid in prods.keys():
            await atualizar_catalogo(pid)
            total += 1
        await i.followup.send(f"✅  **{total}** catálogos atualizados!", ephemeral=True)

class SelProdutoAdmin(discord.ui.View):
    def __init__(self, opts):
        super().__init__(timeout=180)
        self.add_item(ProdAdminSelect(opts))

class ProdAdminSelect(discord.ui.Select):
    def __init__(self, opts):
        super().__init__(placeholder="📦  Selecione um produto...", options=opts)
    async def callback(self, i):
        await i.response.edit_message(content="📦  Gerenciando produto...", view=GerenciarProdutoView(self.values[0]))

class SelProdutoPostar(discord.ui.View):
    def __init__(self, opts):
        super().__init__(timeout=180)
        self.add_item(SelProdutoPostarSelect(opts))

class SelProdutoPostarSelect(discord.ui.Select):
    def __init__(self, opts):
        super().__init__(placeholder="📢  Escolha um produto...", options=opts)
    async def callback(self, i):
        canais = [c for c in i.guild.text_channels if c.permissions_for(i.guild.me).send_messages][:25]
        if not canais:
            await i.response.send_message("❌ Sem canais.", ephemeral=True); return
        opts = [discord.SelectOption(label=f"#{c.name}"[:100], value=str(c.id)) for c in canais]
        await i.response.edit_message(content="📍  Escolha o canal:", view=SelCanalPostar(self.values[0], opts))

class SelCanalPostar(discord.ui.View):
    def __init__(self, pid, opts):
        super().__init__(timeout=180)
        self.add_item(SelCanalPostarSelect(pid, opts))

class SelCanalPostarSelect(discord.ui.Select):
    def __init__(self, pid, opts):
        super().__init__(placeholder="📍  Escolha o canal...", options=opts)
        self.pid = pid
    async def callback(self, i):
        prods = get_produtos()
        p = prods.get(self.pid, {})
        salvo = p.get("catalogo_salvo")
        if salvo:
            await i.response.edit_message(
                content=f"📢  **{p['nome']}** já tem um catálogo salvo. O que deseja?",
                view=EscolherModoCatalogoView(self.pid, self.values[0], salvo)
            )
        else:
            await i.response.send_modal(PostarCatalogoModal(self.pid, self.values[0], salvar=True))

# ═══════════════════════════════════════
#  GERENCIAR PRODUTO
# ═══════════════════════════════════════
class GerenciarProdutoView(discord.ui.View):
    def __init__(self, pid):
        super().__init__(timeout=600)
        self.pid = pid
    def get_p(self): return get_produtos().get(self.pid)

    @discord.ui.button(label="Adicionar Variação", emoji="➕", style=discord.ButtonStyle.success)
    async def addvar(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌", ephemeral=True); return
        await i.response.send_modal(CriarVariacaoModal(self.pid))

    @discord.ui.button(label="Ver Variações", emoji="📋", style=discord.ButtonStyle.primary)
    async def vervar(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌", ephemeral=True); return
        p = self.get_p()
        vs = p.get("variacoes", {})
        if not vs:
            await i.response.send_message("❌ Nenhuma variação.", ephemeral=True); return
        opts = [discord.SelectOption(label=v["nome"][:100], description=f"R$ {v['preco']:.2f} • {len(v.get('keys', []))} keys", value=vid) for vid, v in vs.items()]
        await i.response.send_message("🎁 Variação:", view=SelVariacaoAdmin(self.pid, opts), ephemeral=True)

    @discord.ui.button(label="Editar", emoji="✏️", style=discord.ButtonStyle.secondary)
    async def edit(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌", ephemeral=True); return
        await i.response.send_modal(EditarProdutoModal(self.pid))

    @discord.ui.button(label="Pausar/Ativar", emoji="⏸️", style=discord.ButtonStyle.secondary)
    async def pausar(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌", ephemeral=True); return
        prods = get_produtos()
        prods[self.pid]["ativo"] = not prods[self.pid].get("ativo", True)
        set_produtos(prods)
        status = "🟢  ativo" if prods[self.pid]["ativo"] else "⏸️  pausado"
        await i.response.send_message(f"✅ Produto agora está **{status}**.", ephemeral=True)

    @discord.ui.button(label="Excluir", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delp(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌", ephemeral=True); return
        prods = get_produtos()
        if self.pid in prods:
            nome = prods.pop(self.pid)["nome"]
            set_produtos(prods)
            await i.response.send_message(f"🗑️ Produto **{nome}** excluído.", ephemeral=True)

class SelVariacaoAdmin(discord.ui.View):
    def __init__(self, pid, opts):
        super().__init__(timeout=180)
        self.add_item(SelVariacaoAdminSelect(pid, opts))

class SelVariacaoAdminSelect(discord.ui.Select):
    def __init__(self, pid, opts):
        super().__init__(placeholder="🎁  Selecione uma variação...", options=opts)
        self.pid = pid
    async def callback(self, i):
        await i.response.edit_message(content="🎁  Gerenciando variação...", view=GerenciarVariacaoView(self.pid, self.values[0]))

class GerenciarVariacaoView(discord.ui.View):
    def __init__(self, pid, vid):
        super().__init__(timeout=600)
        self.pid = pid
        self.vid = vid
    def get_v(self): return get_produtos().get(self.pid, {}).get("variacoes", {}).get(self.vid)

    @discord.ui.button(label="Adicionar Keys", emoji="➕", style=discord.ButtonStyle.success)
    async def addk(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌", ephemeral=True); return
        await i.response.send_modal(AddKeysModal(self.pid, self.vid))

    @discord.ui.button(label="Ver Keys", emoji="📋", style=discord.ButtonStyle.primary)
    async def verk(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌", ephemeral=True); return
        v = self.get_v()
        ks = v.get("keys", [])
        txt = "\n".join(f"`{i+1}.` {k}" for i, k in enumerate(ks[:30])) if ks else "*(vazio)*"
        e = discord.Embed(title=f"🔑  Keys de {v['nome']}", description=f"**Total:** `{len(ks)}`\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{txt}", color=0x5865F2)
        if len(ks) > 30: e.set_footer(text=f"Mostrando 30 de {len(ks)}")
        await i.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="Deletar Keys", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delk(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌", ephemeral=True); return
        await i.response.send_modal(DeletarKeysModal(self.pid, self.vid))

    @discord.ui.button(label="Definir Cargo", emoji="🎭", style=discord.ButtonStyle.secondary)
    async def cargo(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌", ephemeral=True); return
        cargos = [c for c in i.guild.roles if not c.is_default() and c.position < i.guild.me.top_role.position][:25]
        if not cargos:
            await i.response.send_message("❌ Sem cargos.", ephemeral=True); return
        opts = [discord.SelectOption(label=c.name[:100], value=str(c.id)) for c in cargos]
        await i.response.send_message("🎭  Escolha o cargo automático desta variação:", view=SelCargoVar(self.pid, self.vid, opts), ephemeral=True)

class SelCargoVar(discord.ui.View):
    def __init__(self, pid, vid, opts):
        super().__init__(timeout=180)
        self.add_item(SelCargoVarSelect(pid, vid, opts))

class SelCargoVarSelect(discord.ui.Select):
    def __init__(self, pid, vid, opts):
        super().__init__(placeholder="🎭  Selecione o cargo...", options=opts)
        self.pid = pid
        self.vid = vid
    async def callback(self, i):
        prods = get_produtos()
        prods[self.pid]["variacoes"][self.vid]["cargo_id"] = self.values[0]
        set_produtos(prods)
        cargo = i.guild.get_role(int(self.values[0]))
        await i.response.send_message(f"✅ Cargo **{cargo.name}** definido.", ephemeral=True)

# ═══════════════════════════════════════
#  COMANDOS
# ═══════════════════════════════════════
@bot.event
async def on_ready():
    bot.add_view(PainelAdminView())
    postados = get_postados()
    for msg_id, dados in postados.items():
        try: bot.add_view(VerOpcoesView(dados["produto_id"]))
        except: pass
    await start_web()
    try:
        bot.tree.copy_global_to(guild=discord.Object(id=GUILD_ID))
        s = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"✅ {len(s)} comandos sincronizados")
    except Exception as e:
        print(f"Sync erro: {e}")
    print(f"🤖 Online: {bot.user}")

@bot.tree.command(name="painel", description="[STAFF] Painel admin")
async def painel(i):
    if not is_staff(i.user):
        await i.response.send_message("❌ Sem permissão.", ephemeral=True); return
    await i.channel.send(embed=embed_painel_admin(i.user), view=PainelAdminView())
    await i.response.send_message("✅ Painel enviado!", ephemeral=True)

@bot.tree.command(name="postar", description="[STAFF] Posta um catálogo")
async def cmd_postar(i):
    if not is_staff(i.user):
        await i.response.send_message("❌ Sem permissão.", ephemeral=True); return
    prods = get_produtos()
    if not prods:
        await i.response.send_message("❌ Nenhum produto.", ephemeral=True); return
    opts = [discord.SelectOption(label=p["nome"][:100], value=pid) for pid, p in list(prods.items())[:25]]
    await i.response.send_message("📢 Escolha o produto:", view=SelProdutoPostar(opts), ephemeral=True)

@bot.tree.command(name="stats", description="[STAFF] Estatísticas")
async def stats(i):
    if not is_staff(i.user):
        await i.response.send_message("❌ Sem permissão.", ephemeral=True); return
    pedidos = get_pedidos()
    pagos = [p for p in pedidos if p["status"] == "entregue"]
    pend = [p for p in pedidos if p["status"] in ("pendente", "aguardando_pagamento", "aguardando_confirmacao")]
    fat = sum(p["preco_final"] for p in pagos)
    e = discord.Embed(title="📊 Estatísticas", color=0x5865F2)
    e.add_field(name="Total", value=f"`{len(pedidos)}`")
    e.add_field(name="✅ Entregues", value=f"`{len(pagos)}`")
    e.add_field(name="⏳ Andamento", value=f"`{len(pend)}`")
    e.add_field(name="💰 Faturamento", value=f"`R$ {fat:.2f}`")
    await i.response.send_message(embed=e, ephemeral=True)

bot.run(TOKEN)
