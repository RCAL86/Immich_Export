import os
import sys
import argparse
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from db import MigrationDB
from immich_client import ImmichClient
from google_photos_client import GooglePhotosClient
from migrator import ImmichToGooglePhotosMigrator

# Carrega variáveis de ambiente do .env
load_dotenv()

console = Console()


def get_config():
    immich_url = os.getenv("IMMICH_URL")
    immich_key = os.getenv("IMMICH_API_KEY")
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    sync_albums = os.getenv("SYNC_ALBUMS", "true").lower() in ("true", "1", "yes")
    inject_exif = os.getenv("INJECT_EXIF", "true").lower() in ("true", "1", "yes")
    delay = float(os.getenv("REQUEST_DELAY_SECONDS", "1.5"))

    return {
        "immich_url": immich_url,
        "immich_key": immich_key,
        "creds_file": creds_file,
        "sync_albums": sync_albums,
        "inject_exif": inject_exif,
        "request_delay": delay
    }


def test_connections():
    config = get_config()
    console.print(Panel.fit("[bold blue]Testando Conexões[/bold blue]"))

    # 1. Teste Immich
    if not config["immich_url"] or not config["immich_key"]:
        console.print("[red]❌ IMMICH_URL ou IMMICH_API_KEY não configurados no arquivo .env![/red]")
        immich_ok = False
    else:
        try:
            with console.status("[yellow]Conectando ao Immich...[/yellow]"):
                client = ImmichClient(config["immich_url"], config["immich_key"])
                info = client.ping()
            console.print(f"[green]✔ Conexão com Immich OK![/green]")
            console.print(f"   👤 Usuário: [cyan]{info.get('user_name')}[/cyan] ({info.get('user_email')})")
            console.print(f"   📦 Versão do Servidor: [cyan]{info.get('server_version')}[/cyan]")
            immich_ok = True
        except Exception as e:
            console.print(f"[red]❌ Falha na conexão com Immich: {e}[/red]")
            immich_ok = False

    # 2. Teste Google Photos
    if not os.path.exists(config["creds_file"]) and not os.path.exists("token.json"):
        console.print(f"[red]❌ Arquivo '{config['creds_file']}' não encontrado! Veja as instruções no README.[/red]")
        google_ok = False
    else:
        try:
            with console.status("[yellow]Verificando autenticação no Google Fotos...[/yellow]"):
                gclient = GooglePhotosClient(config["creds_file"])
            console.print("[green]✔ Autenticação no Google Fotos OK![/green]")
            google_ok = True
        except Exception as e:
            console.print(f"[red]❌ Falha na autenticação do Google Fotos: {e}[/red]")
            google_ok = False

    return immich_ok and google_ok


def show_status():
    config = get_config()
    db = MigrationDB()
    stats = db.get_stats()
    uploaded = stats["uploaded_assets"]
    failed = stats["failed_assets"]
    albums = stats["synced_albums"]

    total_immich = 0
    immich_photos = 0
    immich_videos = 0

    if config["immich_url"] and config["immich_key"]:
        try:
            client = ImmichClient(config["immich_url"], config["immich_key"])
            istats = client.get_statistics()
            immich_photos = istats.get("photos", 0)
            immich_videos = istats.get("videos", 0)
            total_immich = istats.get("total", 0)
        except Exception:
            pass

    table = Table(title="📊 Status e Progresso da Migração")
    table.add_column("Métrica", style="cyan", no_wrap=True)
    table.add_column("Valor", style="magenta")

    if total_immich > 0:
        pct = (uploaded / total_immich) * 100
        remaining = max(0, total_immich - uploaded)
        table.add_row("Total de Itens no Immich", f"{total_immich:,} ({immich_photos:,} fotos, {immich_videos:,} vídeos)".replace(",", "."))
        table.add_row("Transferidos com Sucesso", f"{uploaded:,}".replace(",", "."))
        table.add_row("Itens Restantes", f"{remaining:,}".replace(",", "."))
        table.add_row("Progresso Concluído", f"[bold green]{pct:.1f}%[/bold green]")
    else:
        table.add_row("Fotos/Vídeos Sincronizados com Sucesso", str(uploaded))

    table.add_row("Itens com Falha", str(failed))
    table.add_row("Álbuns Sincronizados", str(albums))

    console.print(table)



def run_sync():
    config = get_config()
    if not config["immich_url"] or not config["immich_key"]:
        console.print("[red]❌ Configure o IMMICH_URL e IMMICH_API_KEY no arquivo .env antes de iniciar![/red]")
        return

    if not os.path.exists(config["creds_file"]) and not os.path.exists("token.json"):
        console.print(f"[red]❌ O arquivo '{config['creds_file']}' precisa estar presente na pasta do projeto![/red]")
        return

    try:
        def log_message(msg: str):
            console.print(msg)

        immich = ImmichClient(config["immich_url"], config["immich_key"])
        google_photos = GooglePhotosClient(config["creds_file"], log_fn=log_message)
        db = MigrationDB()

        migrator = ImmichToGooglePhotosMigrator(
            immich=immich,
            google_photos=google_photos,
            db=db,
            sync_albums=config["sync_albums"],
            inject_exif=config["inject_exif"],
            request_delay=config["request_delay"]
        )

        console.print(Panel.fit(
            f"[bold green]Iniciando Transferência Direta[/bold green]\n"
            f"• Servidor Immich: [cyan]{config['immich_url']}[/cyan]\n"
            f"• Sincronizar Álbuns: [yellow]{'Sim' if config['sync_albums'] else 'Não'}[/yellow]\n"
            f"• Injeção de EXIF: [yellow]{'Sim' if config['inject_exif'] else 'Não'}[/yellow]\n"
            f"• Intervalo entre envios: [yellow]{config['request_delay']}s[/yellow]"
        ))

        migrator.run_migration(log_fn=log_message)

    except Exception as e:
        console.print(f"[bold red]Erro crítico na execução:[/bold red] {e}")


def run_sync_albums():
    config = get_config()
    if not config["immich_url"] or not config["immich_key"]:
        console.print("[red]❌ Configure o IMMICH_URL e IMMICH_API_KEY no arquivo .env![/red]")
        return
    if not os.path.exists(config["creds_file"]) and not os.path.exists("token.json"):
        console.print(f"[red]❌ O arquivo '{config['creds_file']}' precisa estar presente na pasta![/red]")
        return

    try:
        def log_message(msg: str):
            console.print(msg)

        immich = ImmichClient(config["immich_url"], config["immich_key"])
        google_photos = GooglePhotosClient(config["creds_file"], log_fn=log_message)
        db = MigrationDB()

        migrator = ImmichToGooglePhotosMigrator(
            immich=immich,
            google_photos=google_photos,
            db=db,
            sync_albums=True,
            inject_exif=False,
            request_delay=config["request_delay"]
        )

        console.print(Panel.fit("[bold green]Organizando e Vinculando Fotos aos Álbuns do Google Fotos[/bold green]\n[yellow]Isso não faz re-upload de nenhum arquivo![/yellow]"))
        migrator.populate_albums(log_fn=log_message)
        console.print("[bold green]✔ Todos os álbuns foram organizados com sucesso no Google Fotos![/bold green]")
    except Exception as e:
        console.print(f"[bold red]Erro ao sincronizar álbuns:[/bold red] {e}")


def reset_videos():
    db = MigrationDB()
    if Confirm.ask("[bold yellow]Deseja resetar o status de todos os vídeos enviados no banco local para que sejam reenviados com a data corrigida?[/bold yellow]"):
        count = db.reset_video_assets()
        console.print(f"[green]✔ {count} vídeo(s) resetado(s) com sucesso![/green]")
        console.print("[cyan]Certifique-se de apagar os vídeos correspondentes no Google Fotos antes de iniciar a sincronização novamente.[/cyan]")


def interactive_menu():
    while True:
        console.print()
        console.print(Panel.fit(
            "[bold cyan]Immich ➔ Google Photos Migrator[/bold cyan]\n"
            "Migração direta via nuvem com timeline e álbuns preservados",
            border_style="cyan"
        ))

        console.print("1. [green]Iniciar Sincronização / Migração Completa[/green]")
        console.print("2. [yellow]Testar Conexões (Immich e Google Fotos)[/yellow]")
        console.print("3. [blue]Ver Status e Progresso Atual[/blue]")
        console.print("4. [bold cyan]Organizar Álbuns Agora (vincular fotos aos álbuns sem re-upload)[/bold cyan]")
        console.print("5. [magenta]Resetar Vídeos no Banco (para reenviar com datas corrigidas)[/magenta]")
        console.print("6. [red]Sair[/red]")

        choice = Prompt.ask("\nEscolha uma opção", choices=["1", "2", "3", "4", "5", "6"], default="1")

        if choice == "1":
            run_sync()
        elif choice == "2":
            test_connections()
        elif choice == "3":
            show_status()
        elif choice == "4":
            run_sync_albums()
        elif choice == "5":
            reset_videos()
        elif choice == "6":
            console.print("[dim]Até logo![/dim]")
            break


def main():
    parser = argparse.ArgumentParser(description="Immich to Google Photos Direct Migrator")
    parser.add_argument("command", nargs="?", choices=["sync", "test", "status", "sync-albums", "reset-videos", "menu"], default="menu",
                        help="Comando a ser executado (padrão: menu interativo)")
    args = parser.parse_args()

    if args.command == "sync":
        run_sync()
    elif args.command == "test":
        test_connections()
    elif args.command == "status":
        show_status()
    elif args.command == "sync-albums":
        run_sync_albums()
    elif args.command == "reset-videos":
        reset_videos()
    else:
        interactive_menu()




if __name__ == "__main__":
    main()

