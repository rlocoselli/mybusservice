import psycopg2 
from psycopg2.extensions import cursor as PsycopgCursor
import os


def is_sql_log_enabled():
    sql_log_env = os.getenv('SQL_LOG', 'true').strip().lower()
    return sql_log_env not in ('0', 'false', 'no', 'off')


class LoggingCursor(PsycopgCursor):
    def execute(self, query, vars=None):
        try:
            sql = self.mogrify(query, vars).decode("utf-8") if vars is not None else str(query)
        except Exception:
            sql = str(query)

        if is_sql_log_enabled():
            print("[SQL]", sql)
        return super().execute(query, vars)

    def executemany(self, query, vars_list):
        if is_sql_log_enabled():
            print("[SQL][MANY]", str(query))
        return super().executemany(query, vars_list)

def getConnectionCursor(database):
    server = os.environ['SERVER'] 
    conn = psycopg2.connect(
    host=server,
    database=database,
    user=os.environ['USER'],
    password=os.environ['MOT'])
    
    conn.set_client_encoding('UTF8')
    
    cursor = conn.cursor(cursor_factory=LoggingCursor)

    return cursor

def getVersion():
    cursor = getConnectionCursor()

    cursor.execute("SELECT @@version;") 
    row = cursor.fetchone()

    ret = ""

    while row: 
        print(row[0])
        ret = row[0]
        row = cursor.fetchone()
    
    return ret
