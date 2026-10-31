import secrets
import warnings

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configurações da aplicação.

    Tudo aqui é lido de variáveis de ambiente (ou de um arquivo .env local,
    veja .env.example). Nada de segredo fica hardcoded no código-fonte —
    isso evita o que aconteceu antes: a senha do banco de produção e a
    SECRET_KEY foram commitadas e ficaram expostas publicamente no
    histórico do Git.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    PROJECT_NAME: str = "Ryzer"
    PROJECT_VERSION: str = "1.0.0"

    # Por padrão usamos SQLite local, ótimo para rodar o projeto e demonstrar
    # sem depender de nenhuma infraestrutura externa. Em produção, defina
    # DATABASE_URL no ambiente apontando para o Postgres (ou outro banco).
    DATABASE_URL: str = "sqlite:///./ryzer.db"

    # Se SECRET_KEY não vier do ambiente, geramos uma aleatória só para essa
    # execução. Isso é seguro para rodar localmente/demonstrar, mas significa
    # que tokens emitidos antes de um restart deixam de ser válidos depois.
    # Em produção, defina SECRET_KEY no ambiente com um valor fixo e secreto.
    SECRET_KEY: str = secrets.token_hex(32)

    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24


settings = Settings()

# model_fields_set só contém os campos que vieram de uma fonte real (env var
# ou .env) — um valor puramente default (como o secrets.token_hex acima) não
# entra aqui. É assim que sabemos se a SECRET_KEY foi configurada de verdade.
if "SECRET_KEY" not in settings.model_fields_set:
    warnings.warn(
        "SECRET_KEY não definida no ambiente — usando uma chave aleatória "
        "gerada para esta execução. Tokens de login não vão sobreviver a um "
        "restart do servidor. Defina SECRET_KEY no ambiente (ou em um "
        "arquivo .env) antes de colocar isso em produção.",
        stacklevel=1,
    )
