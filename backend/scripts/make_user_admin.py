import asyncio

from app.services.auth_service import update_app_metadata, get_user_by_id


async def main():
    user_id = None

    user = await get_user_by_id(user_id)

    roles = user.metadata.role.roles

    if "admin" not in roles:
        roles.append("admin")
        await update_app_metadata(user)

    # san
    user2 = await get_user_by_id(user_id)
    print(user2.metadata.role.roles)
    print(user2)


if __name__ == "__main__":
    asyncio.run(main())
