import addict

from . import config

POSTGRES = config.database.connection.provider == "postgres"


SQL = addict.Dict(
    {
        "user": "SELECT * FROM users WHERE id = $1",
        "user_by_email": "SELECT * FROM users WHERE email = $1",
        "user_by_username": "SELECT * FROM users WHERE username = $1",
        "update_user_token": "UPDATE users SET token = $1 WHERE id = $2",
        "upsert_user": """
            WITH spotify_user_id AS (
                INSERT INTO spotify_users AS su ("id", "name", "user")
                VALUES ($3, $5, $1)
                ON CONFLICT DO NOTHING
                RETURNING id
            ), country_code AS (
                INSERT INTO countries AS c ("code", "name")
                VALUES ($9, $10)
                ON CONFLICT DO NOTHING
                RETURNING code
            )
                INSERT INTO users AS u (
                    id, email, username, country,
                    display_name, birthdate, token, spotify_premium
                ) VALUES (
                    $1, $2, $3, $4,
                    $5, $6, $7, $8
                ) ON CONFLICT (username) DO UPDATE SET token = EXCLUDED.token
                RETURNING *
        """,
        "user_artist_genre_dislikes": """
           SELECT artist || '|AR' FROM artist_haters ah WHERE ah."user" = $1
           UNION
           SELECT genre || '|GE' FROM genre_haters gh WHERE gh."user" = $1
        """,
        "user_dislikes": """
           SELECT artist || '|AR' FROM artist_haters ah WHERE ah."user" = $1
           UNION
           SELECT genre || '|GE' FROM genre_haters gh WHERE gh."user" = $1
           UNION
           SELECT country || '|CO' FROM country_haters coh WHERE coh."user" = $1
           UNION
           SELECT city || '|CI' FROM city_haters cih WHERE cih."user" = $1
        """,
        "like": """
            DELETE FROM {0}_haters
            WHERE "user" = $1 and {0} = $2
        """,
        "dislike_artist": """
            WITH artist_id AS (
                INSERT INTO artists AS a (id, name, followers, popularity)
                VALUES ($2, $3, $4, $5)
                ON CONFLICT DO NOTHING
                RETURNING a.id
            )
                INSERT INTO {0}_haters ("user", {0})
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
        """,
        "dislike": """
            INSERT INTO {0}_haters ("user", {0})
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
        """,
        "upsert_genre": """
            INSERT INTO genres (name) VALUES $1
            ON CONFLICT DO NOTHING
        """,
        "upsert_country": """
            INSERT INTO countries (code, name)
            VALUES $1, $2
            ON CONFLICT DO NOTHING
        """,
        "upsert_city": """
            INSERT INTO cities (name, country)
            VALUES $1, $2
            ON CONFLICT DO NOTHING
        """,
        "upsert_playlist": """
            INSERT INTO playlists AS p ({fields})
            VALUES ({values})
            ON CONFLICT DO NOTHING
        """,
    }
)

SQL_DEFAULT = addict.Dict(
    {
        "uuid4": "gen_random_uuid()" if POSTGRES else None,
        "now": "(now() at time zone 'utc')" if POSTGRES else None,
        "in_30_days": "(now() at time zone 'utc') + '30 days'" if POSTGRES else None,
        "bool_false": "FALSE" if POSTGRES else "0",
        "bool_true": "TRUE" if POSTGRES else "1",
    }
)
