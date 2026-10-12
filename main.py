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

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        supabase.table("bot_state").upsert({
            "key": "_debug_startup",
            "value": {
                "url_len": len(SUPABASE_URL),
                "key_len": len(SUPABASE_KEY),
                "url_inicio": SUPABASE_URL[:30],
                "key_inicio": SUPABASE_KEY[:20],
                "timestamp": datetime.now().isoformat()
            }
        }).execute()
    except Exception as e:
        pass
else:
    pass

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
#  GERAÇÃO DE IMAGEM DO RECIBO
# ═══════════════════════════════════════
async def gerar_recibo_imagem(pedido):
    try:
        W, H = 800, 900
        fundo = (13, 13, 13)
        vermelho = (237, 66, 69)
        vermelho_escuro = (120, 30, 32)
        branco = (240, 240, 240)
        cinza = (140, 140, 140)
        cinza_escuro = (30, 30, 30)

        img = Image.new("RGB", (W, H), fundo)
        draw = ImageDraw.Draw(img)

        f_titulo = f_grande = f_medio = f_normal = f_pequena = None
        for nome in ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                     "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]:
            try:
                f_titulo = ImageFont.truetype(nome, 26)
                f_grande = ImageFont.truetype(nome, 34)
                f_medio = ImageFont.truetype(nome, 22)
                f_normal = ImageFont.truetype(nome, 18)
                f_pequena = ImageFont.truetype(nome, 14)
                break
            except: continue
        if not f_titulo:
            f_titulo = f_grande = f_medio = f_normal = f_pequena = ImageFont.load_default()

        draw.rectangle([(0, 0), (W, 80)], fill=vermelho_escuro)
        draw.text((30, 25), "QZZ VENDAS COMMUNITY", font=f_titulo, fill=branco)
        draw.text((W - 90, 32), "APP", font=f_normal, fill=branco)
        draw.line([(30, 100), (W - 30, 100)], fill=vermelho, width=2)

        try:
            user = await bot.fetch_user(pedido["comprador_id"])
            avatar_bytes = await user.display_avatar.replace(size=128, format="png").read()
            avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((90, 90), Image.LANCZOS)
            mask = Image.new("L", (90, 90), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 90, 90), fill=255)
            img.paste(avatar, (30, 130), mask)
        except Exception as e:
            print(f"[Avatar] erro: {e}")
            draw.ellipse([(30, 130), (120, 220)], fill=cinza_escuro)

        nome_cliente = pedido.get("comprador_nome", "Cliente")
        if len(nome_cliente) > 22: nome_cliente = nome_cliente[:22] + "..."
        draw.text((140, 145), nome_cliente, font=f_medio, fill=branco)
        draw.text((140, 180), f"ID: {pedido['comprador_id']}", font=f_pequena, fill=cinza)

        draw.text((30, 260), "COMPRA REALIZADA", font=f_grande, fill=vermelho)

        draw.text((30, 340), "CARRINHO", font=f_medio, fill=cinza)
        produto_txt = f"{pedido['produto_nome']} | {pedido['variacao_nome']}"
        if len(produto_txt) > 55: produto_txt = produto_txt[:55] + "..."
        draw.text((30, 375), produto_txt, font=f_normal, fill=branco)

        valor_txt = f"R$ {pedido['preco_final']:.2f}".replace(".", ",")
        bbox = draw.textbbox((0, 0), valor_txt, font=f_medio)
        w_txt = bbox[2] - bbox[0]
        draw.text((W - 30 - w_txt, 372), valor_txt, font=f_medio, fill=branco)

        draw.line([(W - 220, 415), (W - 30, 415)], fill=cinza_escuro, width=1)
        draw.text((30, 435), "SUBTOTAL", font=f_normal, fill=cinza)
        bbox = draw.textbbox((0, 0), valor_txt, font=f_normal)
        w_txt = bbox[2] - bbox[0]
        draw.text((W - 30 - w_txt, 435), valor_txt, font=f_normal, fill=branco)

        box_y1, box_y2 = 510, 590
        draw.rectangle([(30, box_y1), (W - 30, box_y2)], fill=vermelho_escuro)
        draw.rectangle([(30, box_y1), (W - 30, box_y2)], outline=vermelho, width=2)
        draw.text((55, box_y1 + 25), "VALOR PAGO", font=f_medio, fill=branco)
        bbox = draw.textbbox((0, 0), valor_txt, font=f_grande)
        w_txt = bbox[2] - bbox[0]
        draw.text((W - 55 - w_txt, box_y1 + 18), valor_txt, font=f_grande, fill=branco)

        draw.text((30, 640), "DETALHES", font=f_medio, fill=cinza)
        draw.line([(30, 675), (W - 30, 675)], fill=cinza_escuro, width=1)

        draw.text((30, 690), "ID do Pedido", font=f_pequena, fill=cinza)
        draw.text((30, 710), f"#{pedido['id']}", font=f_normal, fill=branco)

        draw.text((280, 690), "Data", font=f_pequena, fill=cinza)
        draw.text((280, 710), pedido.get("pago_em", agora()), font=f_normal, fill=branco)

        draw.text((520, 690), "Entrega", font=f_pequena, fill=cinza)
        draw.text((520, 710), "Enviada no PV", font=f_normal, fill=(87, 242, 135))

        draw.line([(30, 800), (W - 30, 800)], fill=vermelho, width=2)
        draw.text((30, 820), "QZZ COMMUNITY #2K", font=f_medio, fill=cinza)
        draw.text((W - 220, 825), "Obrigado pela compra", font=f_pequena, fill=cinza)
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
                title="🎉 Compra Aprovada!",
                description="**Obrigado pela sua compra!**\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n🔑 **SUA KEY ESTÁ ABAIXO** 👇",
                color=0x57F287, timestamp=datetime.now()
            )
            e.add_field(name="📦 Produto", value=pedido['produto_nome'], inline=True)
            e.add_field(name="🎁 Opção", value=pedido['variacao_nome'], inline=True)
            e.add_field(name="💰 Valor", value=f"`R$ {pedido['preco_final']:.2f}`", inline=True)
            e.add_field(name="🆔 Pedido", value=f"`#{pedido['id']}`", inline=True)
            e.add_field(name="📅 Data", value=f"`{agora()}`", inline=True)
            e.add_field(name="\u200b", value="\u200b", inline=True)
            e.add_field(name="🔑 Key", value=f"```\n{key}\n```", inline=False)
            e.add_field(name="⚠️ Importante", value="Guarde esta key em local seguro.", inline=False)
            e.set_footer(text="QZZ Vendas • Obrigado pela preferência 💚", icon_url=bot.user.display_avatar.url)
            await user.send(embed=e)
        else:
            await user.send(f"✅ Pagamento do pedido **#{pedido['id']}** confirmado!")
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

    # ─── Posta o RECIBO (imagem) no canal de entregas
    if CANAL_ENTREGAS:
        ch = bot.get_channel(CANAL_ENTREGAS)
        if ch:
            try:
                buf = await gerar_recibo_imagem(pedido)
                if buf:
                    file = discord.File(buf, filename=f"recibo_{pedido['id']}.png")
                    e = discord.Embed(
                        title="✅ Nova Compra Realizada!",
                        description=f"👤 <@{pedido['comprador_id']}> acabou de comprar!\n📩 Key enviada no PV.",
                        color=0x57F287,
                        timestamp=datetime.now()
                    )
                    e.set_image(url=f"attachment://recibo_{pedido['id']}.png")
                    e.set_footer(text=f"Pedido #{pedido['id']} • Obrigado pela preferência 💚", icon_url=bot.user.display_avatar.url)
                    await ch.send(embed=e, file=file)
                else:
                    e = discord.Embed(
                        title="✅ Nova Compra Realizada!",
                        description=(
                            f"👤 **Cliente:** <@{pedido['comprador_id']}>\n"
                            f"📦 **Produto:** {pedido['produto_nome']}\n"
                            f"🎁 **Opção:** {pedido['variacao_nome']}\n"
                            f"💰 **Valor:** `R$ {pedido['preco_final']:.2f}`\n"
                            f"🆔 **Pedido:** `#{pedido['id']}`"
                        ),
                        color=0x57F287, timestamp=datetime.now()
                    )
                    await ch.send(embed=e)
            except Exception as e:
                print(f"[Entregas] erro: {e}")

    # ─── Log staff
    if CANAL_LOGS:
        ch = bot.get_channel(CANAL_LOGS)
        if ch:
            e = discord.Embed(title="💸 Nova Venda Aprovada!", description="━━━━━━━━━━━━━━━━━━━━━━━━━━", color=0x57F287, timestamp=datetime.now())
            e.add_field(name="🆔 Pedido", value=f"`#{pedido['id']}`", inline=True)
            e.add_field(name="👤 Cliente", value=f"<@{pedido['comprador_id']}>", inline=True)
            e.add_field(name="💰 Valor", value=f"`R$ {pedido['preco_final']:.2f}`", inline=True)
            e.add_field(name="📦 Produto", value=pedido["produto_nome"], inline=False)
            e.add_field(name="🎁 Opção", value=pedido["variacao_nome"], inline=True)
            e.add_field(name="🎭 Cargo", value=pedido.get("cargo_dado", "—"), inline=True)
            e.add_field(name="🔑 Key", value=f"||`{key}`||" if key else "❌ Sem estoque", inline=False)
            e.set_footer(text="QZZ Vendas • Log automático", icon_url=bot.user.display_avatar.url)
            await ch.send(embed=e)

    # ─── Fecha thread
    if pedido.get("thread_id"):
        try:
            thread = bot.get_channel(int(pedido["thread_id"]))
            if thread:
                e = discord.Embed(
                    title="✅ Pagamento Aprovado!",
                    description="━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n🎉 Sua compra foi confirmada!\n\n📩 **A key foi enviada no seu PV.**\n\n**Thread fechada em 30s...**",
                    color=0x57F287, timestamp=datetime.now()
                )
                await thread.send(embed=e)
                await asyncio.sleep(30)
                try: await thread.edit(archived=True, locked=True)
                except: pass
        except Exception as e:
            print(f"[Thread] erro: {e}")

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
        title="🛠️ Painel de Administração",
        description=f"**Bem-vindo, {user.display_name}!**\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nUse os botões abaixo:",
        color=cfg.get("cor_principal", 0x5865F2), timestamp=datetime.now()
    )
    e.add_field(name="📦 Produtos", value=f"`{len(prods)}`", inline=True)
    e.add_field(name="🔑 Keys", value=f"`{total_keys}`", inline=True)
    e.add_field(name="🏪 Loja", value=f"`{cfg.get('nome_loja', '—')}`", inline=True)
    e.set_footer(text="Sharpify + Supabase", icon_url=bot.user.display_avatar.url)
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
            "variacoes": {}, "ativo": True, "criado_em": agora()
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

class PostarCatalogoModal(discord.ui.Modal, title="📢 Postar Catálogo"):
    titulo = discord.ui.TextInput(label="Título do produto", required=True, max_length=150)
    bullets = discord.ui.TextInput(label="✅ Benefícios (1 por linha)", style=discord.TextStyle.paragraph, required=True, max_length=1000)
    recebe = discord.ui.TextInput(label="📦 O que recebe (1 por linha)", style=discord.TextStyle.paragraph, required=True, max_length=800)
    aviso = discord.ui.TextInput(label="⚠️ Aviso (opcional)", style=discord.TextStyle.paragraph, required=False, max_length=400)
    imagem = discord.ui.TextInput(label="URL da imagem/banner", required=False, max_length=500)

    def __init__(self, pid, canal_id):
        super().__init__()
        self.pid = pid
        self.canal_id = canal_id

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

        linhas = [l.strip() for l in self.bullets.value.split("\n") if l.strip()]
        bullets_txt = "\n".join(f"✅ {l}" for l in linhas)
        recebe_linhas = [l.strip() for l in self.recebe.value.split("\n") if l.strip()]
        recebe_txt = "\n".join(f"✅ {l}" for l in recebe_linhas)

        desc = f"**{self.titulo.value}**\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{bullets_txt}"
        if self.aviso.value.strip(): desc += f"\n\n⚠️ *{self.aviso.value.strip()}*"
        desc += f"\n\n**📦 VOCÊ RECEBE**\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n{recebe_txt}"

        e = discord.Embed(description=desc, color=0xED4245)
        img = (self.imagem.value or p.get("imagem") or "").strip()
        if url_imagem_valida(img):
            try: e.set_image(url=img)
            except: pass
        e.set_footer(text=f"🛒 {p['nome']}  •  Escolha uma opção", icon_url=bot.user.display_avatar.url)
        e.timestamp = datetime.now()

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
        super().__init__(placeholder="🎁 Selecione uma opção...", options=opts, min_values=1, max_values=1)

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
        title="🛒 Detalhes do Pedido",
        description="**Confira antes de prosseguir:**\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        color=0x5865F2, timestamp=datetime.now()
    )
    e.add_field(name="👤 Cliente", value=i.user.mention, inline=True)
    e.add_field(name="🆔 Pedido", value=f"`#{num}`", inline=True)
    e.add_field(name="\u200b", value="\u200b", inline=True)
    e.add_field(name="📦 Produto", value=f"**{p['nome']}**", inline=False)
    e.add_field(name="🎁 Opção", value=f"**{v['nome']}**", inline=True)
    e.add_field(name="💰 Preço", value=f"`R$ {v['preco']:.2f}`", inline=True)
    e.add_field(name="\u200b", value="\u200b", inline=True)
    e.add_field(name="ℹ️ Próximo passo", value="Clique em **➡️ Prosseguir** abaixo.", inline=False)
    if p.get("imagem"): e.set_thumbnail(url=p["imagem"])
    e.set_footer(text="QZZ Vendas • Pagamento via Pix", icon_url=bot.user.display_avatar.url)

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
        pedidos = get_pedidos()
        pedido = next((p for p in pedidos if p["id"] == self.pedido_id), None)
        if not pedido:
            await i.response.send_message("❌ Pedido não encontrado.", ephemeral=True); return
        if i.user.id != pedido["comprador_id"]:
            await i.response.send_message("❌ Só o comprador.", ephemeral=True); return
        b.disabled = True
        await i.response.edit_message(view=self)
        e = discord.Embed(
            title="💳 Método de Pagamento",
            description="**Escolha como pagar:**\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n💠 **Pix** — Aprovação instantânea\n⚡ Entrega automática da key",
            color=0xFEE75C
        )
        e.set_footer(text="Selecione abaixo", icon_url=bot.user.display_avatar.url)
        await i.followup.send(embed=e, view=MetodoPagamentoView(self.pedido_id))

class MetodoPagamentoView(discord.ui.View):
    def __init__(self, pedido_id):
        super().__init__(timeout=600)
        self.pedido_id = pedido_id

    @discord.ui.button(label="Pix", emoji="💳", style=discord.ButtonStyle.primary)
    async def pix(self, i, b):
        pedidos = get_pedidos()
        pedido = next((p for p in pedidos if p["id"] == self.pedido_id), None)
        if not pedido:
            await i.response.send_message("❌ Não encontrado.", ephemeral=True); return
        if i.user.id != pedido["comprador_id"]:
            await i.response.send_message("❌ Só o comprador.", ephemeral=True); return
        b.disabled = True
        try: await i.response.edit_message(view=self)
        except: pass
        try: await i.followup.send("💳 Gerando Pix... ⏳", ephemeral=True)
        except: pass

        resp, err = await sharpify_pagar(
            f"{pedido['produto_nome']} - {pedido['variacao_nome']}",
            f"Pedido #{pedido['id']}",
            pedido["preco_final"]
        )

        if err or not resp:
            await i.followup.send(f"❌ Erro ao gerar Pix.\n```{str(err)[:300]}```")
            return

        d = resp.get("data", resp)
        payment = d.get("payment") or {}
        gdata = (payment.get("gateway") or {}).get("data") or {}
        qr = gdata.get("qrCode") or ""
        copia = gdata.get("code") or ""

        pedido["payment_link_id"] = d.get("id")
        pedido["status"] = "aguardando_pagamento"
        set_pedidos(pedidos)

        e = discord.Embed(
            title="💳 Pagamento via Pix",
            description="**Escaneie o QR Code** com seu banco/app.\nAssim que pagar, a key chega automaticamente! ⚡",
            color=0x57F287, timestamp=datetime.now()
        )
        e.add_field(name="🆔 Pedido", value=f"`#{pedido['id']}`", inline=True)
        e.add_field(name="💰 Valor", value=f"`R$ {pedido['preco_final']:.2f}`", inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True)
        e.add_field(name="📦 Produto", value=f"**{pedido['produto_nome']}**\n└ {pedido['variacao_nome']}", inline=False)
        e.set_footer(text="Aguardando pagamento... ⏳", icon_url=bot.user.display_avatar.url)

        enviado = False
        if qr and qr.startswith("data:image"):
            try:
                header, b64 = qr.split(",", 1)
                img_bytes = base64.b64decode(b64)
                file = discord.File(io.BytesIO(img_bytes), filename="qrcode.png")
                e.set_image(url="attachment://qrcode.png")
                await i.followup.send(embed=e, file=file)
                enviado = True
            except Exception as ex: print(f"[QR] {ex}")
        if not enviado:
            await i.followup.send(embed=e)

        if copia:
            e2 = discord.Embed(
                title="📋 Pix Copia e Cola",
                description=f"**Copie e cole no seu banco:**\n\n```\n{copia}\n```",
                color=0x57F287
            )
            e2.set_footer(text=f"Pedido #{pedido['id']}", icon_url=bot.user.display_avatar.url)
            await i.followup.send(embed=e2)

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
        opts = [discord.SelectOption(label=p["nome"][:100], value=pid) for pid, p in list(prods.items())[:25]]
        await i.response.send_message("📢 Escolha o produto:", view=SelProdutoPostar(opts), ephemeral=True)

    @discord.ui.button(label="Estatísticas", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="adm_stats")
    async def stats(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌ Sem permissão.", ephemeral=True); return
        pedidos = get_pedidos()
        pagos = [p for p in pedidos if p["status"] == "entregue"]
        pend = [p for p in pedidos if p["status"] in ("pendente", "aguardando_pagamento", "aguardando_confirmacao")]
        fat = sum(p["preco_final"] for p in pagos)
        e = discord.Embed(title="📊 Estatísticas", description="━━━━━━━━━━━━━━━━━━━━━━━━━━", color=0x5865F2, timestamp=datetime.now())
        e.add_field(name="🛒 Total", value=f"`{len(pedidos)}`", inline=True)
        e.add_field(name="✅ Entregues", value=f"`{len(pagos)}`", inline=True)
        e.add_field(name="⏳ Andamento", value=f"`{len(pend)}`", inline=True)
        e.add_field(name="💰 Faturamento", value=f"`R$ {fat:.2f}`", inline=False)
        e.set_footer(text="QZZ Vendas", icon_url=bot.user.display_avatar.url)
        await i.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="Resumo Estoque", emoji="🔑", style=discord.ButtonStyle.secondary, custom_id="adm_est")
    async def estoque(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌ Sem permissão.", ephemeral=True); return
        prods = get_produtos()
        if not prods:
            await i.response.send_message("❌ Nenhum produto.", ephemeral=True); return
        e = discord.Embed(title="🔑 Resumo de Estoque", description="━━━━━━━━━━━━━━━━━━━━━━━━━━", color=0x5865F2, timestamp=datetime.now())
        total = 0
        for p in prods.values():
            linhas = []
            for v in p.get("variacoes", {}).values():
                qtd = len(v.get("keys", []))
                total += qtd
                emoji = "🟢" if qtd > 5 else ("🟡" if qtd > 0 else "🔴")
                linhas.append(f"{emoji} {v['nome']} — `{qtd}`")
            if linhas: e.add_field(name=f"📦 {p['nome']}", value="\n".join(linhas), inline=False)
        e.set_footer(text=f"Total: {total} keys", icon_url=bot.user.display_avatar.url)
        await i.response.send_message(embed=e, ephemeral=True)

class SelProdutoAdmin(discord.ui.View):
    def __init__(self, opts):
        super().__init__(timeout=180)
        self.add_item(ProdAdminSelect(opts))

class ProdAdminSelect(discord.ui.Select):
    def __init__(self, opts):
        super().__init__(placeholder="📦 Selecione...", options=opts)
    async def callback(self, i):
        await i.response.edit_message(content="📦 Gerenciando...", view=GerenciarProdutoView(self.values[0]))

class SelProdutoPostar(discord.ui.View):
    def __init__(self, opts):
        super().__init__(timeout=180)
        self.add_item(SelProdutoPostarSelect(opts))

class SelProdutoPostarSelect(discord.ui.Select):
    def __init__(self, opts):
        super().__init__(placeholder="📢 Produto...", options=opts)
    async def callback(self, i):
        canais = [c for c in i.guild.text_channels if c.permissions_for(i.guild.me).send_messages][:25]
        if not canais:
            await i.response.send_message("❌ Sem canais.", ephemeral=True); return
        opts = [discord.SelectOption(label=f"#{c.name}"[:100], value=str(c.id)) for c in canais]
        await i.response.edit_message(content="📍 Canal:", view=SelCanalPostar(self.values[0], opts))

class SelCanalPostar(discord.ui.View):
    def __init__(self, pid, opts):
        super().__init__(timeout=180)
        self.add_item(SelCanalPostarSelect(pid, opts))

class SelCanalPostarSelect(discord.ui.Select):
    def __init__(self, pid, opts):
        super().__init__(placeholder="📍 Canal...", options=opts)
        self.pid = pid
    async def callback(self, i):
        await i.response.send_modal(PostarCatalogoModal(self.pid, self.values[0]))

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
        status = "🟢 ativo" if prods[self.pid]["ativo"] else "⏸️ pausado"
        await i.response.send_message(f"✅ {status}.", ephemeral=True)

    @discord.ui.button(label="Excluir", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delp(self, i, b):
        if not is_staff(i.user):
            await i.response.send_message("❌", ephemeral=True); return
        prods = get_produtos()
        if self.pid in prods:
            nome = prods.pop(self.pid)["nome"]
            set_produtos(prods)
            await i.response.send_message(f"🗑️ **{nome}** excluído.", ephemeral=True)

class SelVariacaoAdmin(discord.ui.View):
    def __init__(self, pid, opts):
        super().__init__(timeout=180)
        self.add_item(SelVariacaoAdminSelect(pid, opts))

class SelVariacaoAdminSelect(discord.ui.Select):
    def __init__(self, pid, opts):
        super().__init__(placeholder="🎁 Variação...", options=opts)
        self.pid = pid
    async def callback(self, i):
        await i.response.edit_message(content="🎁 Gerenciando...", view=GerenciarVariacaoView(self.pid, self.values[0]))

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
        e = discord.Embed(title=f"🔑 {v['nome']}", description=f"**Total:** `{len(ks)}`\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{txt}", color=0x5865F2)
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
        await i.response.send_message("🎭 Cargo:", view=SelCargoVar(self.pid, self.vid, opts), ephemeral=True)

class SelCargoVar(discord.ui.View):
    def __init__(self, pid, vid, opts):
        super().__init__(timeout=180)
        self.add_item(SelCargoVarSelect(pid, vid, opts))

class SelCargoVarSelect(discord.ui.Select):
    def __init__(self, pid, vid, opts):
        super().__init__(placeholder="🎭 Cargo...", options=opts)
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
    await i.response.send_message("✅ Enviado!", ephemeral=True)

@bot.tree.command(name="postar", description="[STAFF] Posta um catálogo")
async def cmd_postar(i):
    if not is_staff(i.user):
        await i.response.send_message("❌ Sem permissão.", ephemeral=True); return
    prods = get_produtos()
    if not prods:
        await i.response.send_message("❌ Nenhum produto.", ephemeral=True); return
    opts = [discord.SelectOption(label=p["nome"][:100], value=pid) for pid, p in list(prods.items())[:25]]
    await i.response.send_message("📢 Produto:", view=SelProdutoPostar(opts), ephemeral=True)

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
