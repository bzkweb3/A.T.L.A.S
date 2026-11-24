"""Interactive local-only owner bootstrap and explicit password recovery."""

import argparse
import getpass

from backend.app.core.auth import AuthService
from backend.app.core.config import load_settings
from backend.app.persistence.auth_repository import AuthRepository
from backend.app.persistence.sqlite import SQLiteDatabase


def main() -> None:
    parser = argparse.ArgumentParser(description="Configuração local da senha mestra A.T.L.A.S.")
    parser.add_argument("action", choices=("create-owner", "recover-owner"))
    args = parser.parse_args()
    database = SQLiteDatabase(load_settings().database_path)
    repository = AuthRepository(database)
    if args.action == "create-owner":
        if repository.owner_exists():
            raise SystemExit("Já existe proprietário configurado. Use recover-owner para recuperação explícita.")
    else:
        if not repository.owner_exists():
            raise SystemExit("Não existe proprietário para recuperar.")
        confirmation = input('Para revogar todas as sessões e redefinir a senha, digite exatamente "RECUPERAR A.T.L.A.S.": ')
        if confirmation != "RECUPERAR A.T.L.A.S.":
            raise SystemExit("Confirmação não corresponde; nenhuma alteração feita.")
    password = getpass.getpass("Nova senha mestra (mínimo 14 caracteres): ")
    repeated = getpass.getpass("Repita a senha mestra: ")
    if password != repeated:
        raise SystemExit("As senhas não correspondem.")
    try:
        password_hash = AuthService.hash_password(password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if args.action == "create-owner":
        if not repository.create_owner(password_hash):
            raise SystemExit("O proprietário foi configurado por outro processo; nenhuma senha foi sobrescrita.")
    else:
        repository.reset_owner(password_hash)
    print("Senha mestra configurada com sucesso.")


if __name__ == "__main__":
    main()
