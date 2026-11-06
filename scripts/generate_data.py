"""
Gera os dados de RH da Nortia Serviços (empresa fictícia): 30 meses de operação simulados mês a mês.

Saídas em data/raw:
    rh/colaboradores_AAAA-MM.csv   foto mensal do sistema de RH (o sistema muda em jan/2024)
    folha/folha_AAAA-MM.csv        folha de pagamento
    ponto/afastamentos.json        férias, atestados e licenças

A simulação gera a verdade primeiro e a sujeira entra só na exportação. O gabarito em
data/external permite conferir o que o pipeline recuperou.
"""

from __future__ import annotations

import json
import random
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEMENTE = 7
rng = np.random.default_rng(SEMENTE)
random.seed(SEMENTE)

RAIZ = Path(__file__).resolve().parents[1]
RAW, EXTERNOS = RAIZ / "data" / "raw", RAIZ / "data" / "external"
MESES = pd.period_range("2023-01", "2025-06", freq="M")
MIGRACAO = pd.Period("2024-01", "M")          # troca do sistema de RH
REESTRUTURACAO = pd.Period("2024-08", "M")    # corte no Atendimento, que vira Customer Success

NIVEIS = ["Júnior", "Pleno", "Sênior", "Coordenador", "Gerente", "Diretor", "Presidente"]
MULTIPLICADOR = dict(zip(NIVEIS, [1.0, 1.4, 1.9, 2.4, 3.6, 6.0, 11.0]))
DEPTOS = {
    "Tecnologia": dict(headcount=110, cargo="Engenheiro de Software", turnover=0.012, base=7500),
    "Operações": dict(headcount=220, cargo="Operador de Logística", turnover=0.022, base=2600),
    "Atendimento": dict(headcount=150, cargo="Atendente", turnover=0.033, base=2300),
    "Comercial": dict(headcount=70, cargo="Consultor Comercial", turnover=0.020, base=4200),
    "Financeiro": dict(headcount=35, cargo="Analista Financeiro", turnover=0.010, base=5200),
    "Pessoas": dict(headcount=20, cargo="Analista de RH", turnover=0.010, base=4800),
}
UNIDADES = ["São Paulo", "Campinas", "Recife", "Curitiba"]
GAP_GENERO = {"Tecnologia": 0.92, "Comercial": 0.93}     # mulheres ganham menos nestas áreas, no mesmo cargo
MOTIVOS_VOLUNTARIOS = ["Pedido de demissão"]
MOTIVOS_INVOLUNTARIOS = ["Dispensa sem justa causa", "Dispensa sem justa causa", "Dispensa sem justa causa", "Justa causa"]

NOMES_F = "Ana Beatriz Camila Daniela Eduarda Fernanda Gabriela Helena Isabela Júlia Larissa Mariana Natália Patrícia Renata Sofia Tatiana Vitória".split()
NOMES_M = "André Bruno Caio Daniel Eduardo Felipe Gustavo Henrique Igor João Lucas Marcelo Nicolas Otávio Pedro Rafael Thiago Vinícius".split()
SOBRENOMES = "Almeida Araújo Barbosa Cardoso Carvalho Castro Costa Dias Fernandes Ferreira Gomes Lima Martins Melo Moreira Oliveira Pereira Ribeiro Rocha Santos Silva Souza Teixeira Vieira".split()


@dataclass(frozen=True)
class Pessoa:
    cpf: str
    nome: str
    nascimento: date
    genero: str


@dataclass
class Vinculo:
    matricula: int
    pessoa: Pessoa
    admissao: date
    depto: str
    nivel: str
    unidade: str
    gestor: int | None
    salario: float
    contrato: str
    vigencia: date
    desligamento: date | None = None
    motivo: str | None = None

    @property
    def cargo(self) -> str:
        if self.nivel == "Presidente":
            return "Presidente"
        if NIVEIS.index(self.nivel) >= 3:
            return f"{self.nivel} de {self.depto}"
        return f"{DEPTOS[self.depto]['cargo']} {self.nivel}"


def gerar_cpf() -> str:
    numeros = [int(d) for d in rng.integers(0, 10, 9)]
    if rng.random() < 0.12:
        numeros[0] = 0                          # zeros à esquerda somem em exportações numéricas
    for tamanho in (9, 10):
        soma = sum(n * (tamanho + 1 - i) for i, n in enumerate(numeros))
        resto = soma * 10 % 11
        numeros.append(0 if resto == 10 else resto)
    return "".join(map(str, numeros))


def nova_pessoa(admissao: date) -> Pessoa:
    genero = "F" if rng.random() < 0.47 else "M"
    primeiro = random.choice(NOMES_F if genero == "F" else NOMES_M)
    nome = f"{primeiro} {random.choice(SOBRENOMES)} {random.choice(SOBRENOMES)}"
    idade = int(np.clip(rng.normal(33, 8), 18, 62))
    return Pessoa(gerar_cpf(), nome, date(admissao.year - idade, int(rng.integers(1, 13)), int(rng.integers(1, 29))), genero)


class Empresa:
    def __init__(self) -> None:
        self.vinculos: dict[int, Vinculo] = {}
        self.proxima = 10001
        self.recontratacoes = 0
        self.gestor_problema: int | None = None

    def ativos(self, depto: str | None = None) -> list[Vinculo]:
        return [v for v in self.vinculos.values() if v.desligamento is None and depto in (None, v.depto)]

    def salario_de(self, depto: str, nivel: str, pessoa: Pessoa) -> float:
        valor = DEPTOS[depto]["base"] * MULTIPLICADOR[nivel] if depto else 0
        valor *= float(rng.lognormal(0, 0.06))
        if pessoa.genero == "F" and NIVEIS.index(nivel) < 4:
            valor *= GAP_GENERO.get(depto, 0.99)
        return round(valor, 2)

    def contratar(self, depto: str, nivel: str, gestor: int | None, admissao: date, pessoa: Pessoa | None = None) -> Vinculo:
        pessoa = pessoa or nova_pessoa(admissao)
        temporario = depto == "Operações" and NIVEIS.index(nivel) < 2 and rng.random() < 0.1
        vinculo = Vinculo(self.proxima, pessoa, admissao, depto, nivel, random.choice(UNIDADES), gestor, self.salario_de(depto, nivel, pessoa),
                          "Temporário" if temporario else "CLT", admissao)
        self.vinculos[self.proxima] = vinculo
        self.proxima += 1
        return vinculo

    def estrutura_inicial(self) -> None:
        def admissao_antiga() -> date:
            return date(int(rng.integers(2015, 2023)), int(rng.integers(1, 13)), int(rng.integers(1, 28)))

        presidente = self.contratar("Pessoas", "Presidente", None, date(2014, 3, 3))
        presidente.salario = 95000.0
        for depto, regra in DEPTOS.items():
            diretor = self.contratar(depto, "Diretor", presidente.matricula, admissao_antiga())
            gerentes = [self.contratar(depto, "Gerente", diretor.matricula, admissao_antiga()) for _ in range(max(1, regra["headcount"] // 50))]
            coordenadores = [self.contratar(depto, "Coordenador", gerentes[i % len(gerentes)].matricula, admissao_antiga())
                             for i in range(max(1, regra["headcount"] // 12))]
            for i in range(regra["headcount"]):
                nivel = random.choices(NIVEIS[:3], weights=[5, 3, 2])[0]
                self.contratar(depto, nivel, coordenadores[i % len(coordenadores)].matricula, admissao_antiga())
        self.gestor_problema = next(v.matricula for v in self.ativos("Comercial") if v.nivel == "Coordenador")

    def mudar(self, vinculo: Vinculo, vigencia: date, **campos) -> None:
        for campo, valor in campos.items():
            setattr(vinculo, campo, valor)
        vinculo.vigencia = max(vigencia, vinculo.vigencia)

    def coordenador_com_vaga(self, depto: str) -> int:
        coordenadores = [v for v in self.ativos(depto) if v.nivel == "Coordenador"]
        equipes = {c.matricula: 0 for c in coordenadores}
        for v in self.ativos(depto):
            if v.gestor in equipes:
                equipes[v.gestor] += 1
        return min(equipes, key=equipes.get)

    def substituir_gestor(self, saiu: Vinculo) -> None:
        equipe = [v for v in self.ativos() if v.gestor == saiu.matricula]
        if not equipe:
            return
        data = saiu.desligamento + timedelta(days=1)
        seniores = [v for v in equipe if v.nivel == "Sênior"]
        if saiu.nivel == "Coordenador" and seniores:
            novo = random.choice(seniores)
            self.mudar(novo, data, nivel="Coordenador", salario=round(novo.salario * 1.2, 2), gestor=saiu.gestor)
        else:
            novo = self.contratar(saiu.depto, saiu.nivel, saiu.gestor, data)
        for v in equipe:
            if v is not novo:
                self.mudar(v, data, gestor=novo.matricula)


def dia_do_mes(mes: pd.Period, limite: int = 27) -> date:
    return date(mes.year, mes.month, int(rng.integers(1, limite + 1)))


def simular() -> tuple[list[tuple], list[dict], dict]:
    """Devolve as fotos mensais verdadeiras, a folha e os fatos para o gabarito."""
    empresa = Empresa()
    empresa.estrutura_inicial()
    fotos, folha, afastamentos = [], [], []
    silenciosos, fantasmas = {}, {}
    desligados: list[Vinculo] = []
    ciclo: dict = {}
    headcount = {}

    for indice, mes in enumerate(MESES):
        inicio, fim = mes.start_time.date(), mes.end_time.date()
        retroativos: dict[int, float] = {}

        if mes.month == 9:                                    # dissídio coletivo
            for v in empresa.ativos():
                if NIVEIS.index(v.nivel) <= 4:
                    empresa.mudar(v, inicio, salario=round(v.salario * 1.05, 2))

        for v in empresa.ativos():                            # promoções
            indice_nivel = NIVEIS.index(v.nivel)
            if indice_nivel < 2 and (fim - v.admissao).days >= 365 and rng.random() < 0.012:
                novo_salario = round(v.salario * 1.13, 2)
                vigencia = dia_do_mes(mes)
                if rng.random() < 0.15:                       # lançada com atraso: vale desde o mês anterior
                    anterior = dia_do_mes(mes - 1)
                    if anterior > v.vigencia:
                        vigencia = anterior
                        retroativos[v.matricula] = round(novo_salario - v.salario, 2)
                empresa.mudar(v, vigencia, nivel=NIVEIS[indice_nivel + 1], salario=novo_salario)
            elif v.depto == "Operações" and rng.random() < 0.003:
                empresa.mudar(v, dia_do_mes(mes), unidade=random.choice(UNIDADES))

        cortes = set()
        if mes == REESTRUTURACAO:
            equipe = [v for v in empresa.ativos("Atendimento") if NIVEIS.index(v.nivel) < 3]
            cortes = {v.matricula for v in random.sample(equipe, int(len(equipe) * 0.25))}

        for v in empresa.ativos():                            # saídas
            if v.nivel == "Presidente" or v.matricula == empresa.gestor_problema:
                continue
            risco = DEPTOS[v.depto]["turnover"]
            risco *= 2 if (fim - v.admissao).days < 90 else 1
            risco *= 3.5 if v.gestor == empresa.gestor_problema else 1
            risco *= 0.5 if NIVEIS.index(v.nivel) >= 4 else 1
            if v.matricula in cortes:
                v.desligamento, v.motivo = date(mes.year, mes.month, 15), "Dispensa sem justa causa"
            elif rng.random() < risco:
                v.desligamento = max(dia_do_mes(mes), v.admissao + timedelta(days=1))
                if v.desligamento > fim:
                    v.desligamento = None
                    continue
                if v.contrato == "Temporário":
                    v.motivo = "Fim de contrato"
                else:
                    v.motivo = random.choice(MOTIVOS_VOLUNTARIOS if rng.random() < 0.65 else MOTIVOS_INVOLUNTARIOS)
            else:
                continue
            desligados.append(v)
            empresa.substituir_gestor(v)
            lider = NIVEIS.index(v.nivel) >= 3
            if not lider and len(silenciosos) < 8 and rng.random() < 0.02:
                silenciosos[v.matricula] = mes        # some da foto, sem data de desligamento
            elif not lider and v.matricula not in cortes and len(fantasmas) < 6 and rng.random() < 0.02:
                fantasmas[v.matricula] = int(rng.integers(1, 4))   # segue na folha depois de sair

        if mes == pd.Period("2024-03", "M"):                  # erro de cadastro: gerente subordinado à própria equipe
            gerente = next(v for v in empresa.ativos("Financeiro") if v.nivel == "Gerente")
            subordinado = next(v for v in empresa.ativos() if v.gestor == gerente.matricula)
            ciclo = {"gerente": gerente.matricula, "subordinado": subordinado.matricula, "gestor_original": gerente.gestor}
            empresa.mudar(gerente, inicio, gestor=subordinado.matricula)
        if mes == pd.Period("2024-05", "M"):
            empresa.mudar(empresa.vinculos[ciclo["gerente"]], inicio, gestor=ciclo["gestor_original"])

        for depto, regra in DEPTOS.items():                   # contratações
            alvo = regra["headcount"] * (1 + 0.005 * indice)
            if depto == "Atendimento" and mes >= REESTRUTURACAO:
                alvo *= 0.78
            while sum(1 for v in empresa.ativos(depto) if NIVEIS.index(v.nivel) < 3) < alvo:
                gestor = empresa.coordenador_com_vaga(depto)
                nivel = random.choices(NIVEIS[:3], weights=[5, 3, 2])[0]
                ativos_cpf = {v.pessoa.cpf for v in empresa.ativos()}
                elegiveis = [v for v in desligados if v.depto == depto and v.motivo == "Pedido de demissão" and v.pessoa.cpf not in ativos_cpf
                             and (inicio - v.desligamento).days >= 90 and v.matricula not in silenciosos and v.matricula not in fantasmas]
                pessoa = None
                if elegiveis and rng.random() < 0.05:
                    pessoa = random.choice(elegiveis).pessoa
                    empresa.recontratacoes += 1
                empresa.contratar(depto, nivel, gestor, dia_do_mes(mes), pessoa)

        presentes = [v for v in empresa.vinculos.values() if v.desligamento is None or v.desligamento >= inicio]
        fotos.append((mes, [replace(v) for v in presentes if v.matricula not in silenciosos or silenciosos[v.matricula] > mes]))
        headcount[str(mes)] = sum(1 for v in presentes if v.desligamento is None or v.desligamento > fim)

        for v in presentes:
            if v.matricula in silenciosos and silenciosos[v.matricula] <= mes:
                continue
            extras = round(v.salario * float(rng.uniform(0, 0.12)), 2) if v.depto == "Operações" and NIVEIS.index(v.nivel) < 3 else 0.0
            folha.append(_linha_folha(v, mes, extras, retroativos.get(v.matricula, 0.0)))
            afastamentos += _afastamentos_do_mes(v, mes)
        for matricula, restante in list(fantasmas.items()):
            v = empresa.vinculos[matricula]
            if v.desligamento < inicio and restante > 0:
                folha.append(_linha_folha(v, mes, 0.0, 0.0))
                fantasmas[matricula] = restante - 1

    fatos = {
        "empresa": empresa, "headcount": headcount, "silenciosos": sorted(silenciosos), "fantasmas": sorted(fantasmas), "ciclo": ciclo,
        "afastamentos": afastamentos,
    }
    return fotos, folha, fatos


def _linha_folha(v: Vinculo, mes: pd.Period, extras: float, retroativo: float) -> dict:
    bruto = v.salario + extras + retroativo
    descontos = round(bruto * 0.17, 2)
    return {"matricula": v.matricula, "competencia": mes, "salario_base": v.salario, "horas_extras": extras, "retroativo": retroativo,
            "descontos": descontos, "liquido": round(bruto - descontos, 2)}


def _afastamentos_do_mes(v: Vinculo, mes: pd.Period) -> list[dict]:
    if v.desligamento is not None:
        return []
    registros = []
    chance_atestado = 0.06 if v.depto == "Atendimento" else 0.03
    if rng.random() < chance_atestado:
        inicio = dia_do_mes(mes)
        registros.append({"matricula": v.matricula, "tipo": "atestado", "inicio": inicio, "fim": inicio + timedelta(days=int(rng.integers(0, 5))),
                          "cid": random.choice(["J06", "M54", "A09", "F41", "K29"])})
    if rng.random() < 0.08 and (mes.end_time.date() - v.admissao).days > 365:
        inicio = dia_do_mes(mes)
        registros.append({"matricula": v.matricula, "tipo": "ferias", "inicio": inicio, "fim": inicio + timedelta(days=int(rng.choice([9, 14, 19, 29]))), "cid": None})
    if v.pessoa.genero == "F" and rng.random() < 0.001:
        inicio = dia_do_mes(mes)
        registros.append({"matricula": v.matricula, "tipo": "licenca_maternidade", "inicio": inicio, "fim": inicio + timedelta(days=119), "cid": None})
    return registros


# ---- exportação: a sujeira entra aqui ----

CARGO_ANTIGO = {"Engenheiro de Software": "ENG SOFTWARE", "Operador de Logística": "OPER LOGISTICA", "Atendente": "ATENDENTE",
                "Consultor Comercial": "CONS COMERCIAL", "Analista Financeiro": "ANL FINANCEIRO", "Analista de RH": "ANL RH"}
NIVEL_ANTIGO = {"Júnior": "JR", "Pleno": "PL", "Sênior": "SR"}


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def cargo_antigo(v: Vinculo) -> str:
    if v.nivel in NIVEL_ANTIGO:
        return f"{CARGO_ANTIGO[DEPTOS[v.depto]['cargo']]} {NIVEL_ANTIGO[v.nivel]}"
    return _sem_acento(v.cargo).upper()


def linha_da_foto(v: Vinculo, mes: pd.Period) -> dict:
    area = "Customer Success" if v.depto == "Atendimento" and mes >= REESTRUTURACAO else v.depto
    return {"matricula": v.matricula, "nome": v.pessoa.nome, "cpf": v.pessoa.cpf, "nascimento": v.pessoa.nascimento, "genero": v.pessoa.genero,
            "admissao": v.admissao, "desligamento": v.desligamento, "motivo": v.motivo, "cargo": v.cargo, "cargo_antigo": cargo_antigo(v),
            "area": area, "unidade": v.unidade, "gestor": v.gestor, "salario": v.salario, "contrato": v.contrato, "vigencia": v.vigencia}


def sujar(df: pd.DataFrame, mes: pd.Period, contagem: dict) -> pd.DataFrame:
    df = df.copy()
    sem_saida = df.index[df["desligamento"].isna() & (df["gestor"].notna())]

    def sortear(taxa: float, minimo: int = 0) -> pd.Index:
        quantidade = max(minimo, int(rng.binomial(len(sem_saida), taxa)))
        return pd.Index(rng.choice(sem_saida, quantidade, replace=False))

    linhas = sortear(0.0012)
    df["salario"] = df["salario"].astype(float)
    df.loc[linhas, "salario"] = df.loc[linhas, "salario"] * rng.choice([10, 0.1], len(linhas))
    contagem["salario_digitado_errado"] += len(linhas)

    linhas = sortear(0.0006)
    for i in linhas:                                  # troca um dígito: o CPF deixa de ser válido
        cpf = df.at[i, "cpf"]
        df.at[i, "cpf"] = cpf[:-1] + str((int(cpf[-1]) + 3) % 10)
    contagem["cpf_invalido"] += len(linhas)

    linhas = sortear(0.0006)
    df["gestor"] = df["gestor"].astype("object")
    df.loc[linhas, "gestor"] = 99999
    contagem["gestor_inexistente"] += len(linhas)

    linhas = sortear(0.0004)
    df["admissao"] = df["admissao"].astype("object")
    df.loc[linhas, "admissao"] = date(2031, 1, 1)
    contagem["admissao_no_futuro"] += len(linhas)

    duplicadas = df.loc[sortear(0.003)].copy()        # a mesma pessoa exportada de novo, com vigência anterior
    duplicadas["vigencia"] = duplicadas["vigencia"].map(lambda d: d - timedelta(days=30))
    duplicadas["salario"] = (duplicadas["salario"] * 0.97).round(2)
    contagem["linha_duplicada_antiga"] += len(duplicadas)
    return pd.concat([df, duplicadas], ignore_index=True).sample(frac=1, random_state=int(rng.integers(1e9)))


def _br(valor: float) -> str:
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def exportar_antigo(df: pd.DataFrame, destino: Path) -> None:
    """Sistema antigo: latin-1, ponto e vírgula, tudo em maiúsculas, CPF numérico, datas brasileiras."""
    data = lambda s: s.map(lambda d: d.strftime("%d/%m/%Y") if pd.notna(d) else "")
    saida = pd.DataFrame({
        "MATRICULA": df["matricula"], "NOME": df["nome"].map(lambda n: "  " + _sem_acento(n).upper() if rng.random() < 0.02 else _sem_acento(n).upper()),
        "CPF": df["cpf"].str.lstrip("0"), "DT_NASC": data(df["nascimento"]), "SEXO": df["genero"], "DT_ADMISSAO": data(df["admissao"]),
        "DT_DESLIG": data(df["desligamento"]), "MOT_DESLIG": df["motivo"].map(lambda m: _sem_acento(m).upper() if pd.notna(m) else ""),
        "CARGO": df["cargo_antigo"], "DEPTO": df["area"].map(lambda a: _sem_acento(a).upper()), "UNIDADE": df["unidade"].map(lambda u: _sem_acento(u).upper()),
        "MAT_GESTOR": df["gestor"].map(lambda g: "" if pd.isna(g) else str(int(g))), "SALARIO": df["salario"].map(_br),
        "TP_CONTRATO": df["contrato"].map(lambda c: _sem_acento(c).upper()), "INI_VIGENCIA": data(df["vigencia"]),
    })
    saida.to_csv(destino, sep=";", index=False, encoding="latin-1")


def exportar_novo(df: pd.DataFrame, destino: Path) -> None:
    """Sistema novo: UTF-8, vírgula, datas ISO, CPF com máscara, matrícula com zeros e gênero por extenso."""
    data = lambda s: s.map(lambda d: d.isoformat() if pd.notna(d) else "")
    cpf = df["cpf"].map(lambda c: f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}")
    saida = pd.DataFrame({
        "matricula": df["matricula"].map(lambda m: f"{m:07d}"), "nome_completo": df["nome"], "cpf": cpf, "data_nascimento": data(df["nascimento"]),
        "genero": df["genero"].map({"F": "Feminino", "M": "Masculino"}), "data_admissao": data(df["admissao"]), "data_desligamento": data(df["desligamento"]),
        "motivo_desligamento": df["motivo"].fillna(""), "cargo": df["cargo"], "area": df["area"], "unidade": df["unidade"],
        "matricula_gestor": df["gestor"].map(lambda g: "" if pd.isna(g) else f"{int(g):07d}"), "salario_base": df["salario"].round(2),
        "contrato": df["contrato"], "inicio_vigencia": data(df["vigencia"]),
    })
    saida.to_csv(destino, index=False, encoding="utf-8")


def exportar_folha(linhas: list[dict]) -> None:
    pasta = RAW / "folha"
    pasta.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(linhas)
    for mes, grupo in df.groupby("competencia"):
        repetidas = grupo.sample(frac=0.002, random_state=int(rng.integers(1e9)))
        saida = pd.concat([grupo, repetidas]).assign(competencia=f"{mes.month:02d}/{mes.year}")
        for coluna in ["salario_base", "horas_extras", "retroativo", "descontos", "liquido"]:
            saida[coluna] = saida[coluna].map(_br)
        saida.to_csv(pasta / f"folha_{mes}.csv", sep=";", index=False)


def exportar_afastamentos(registros: list[dict]) -> dict:
    """JSON aninhado por matrícula. O CID é dado de saúde e não deve passar da ingestão."""
    variantes = {"ferias": ["ferias", "FERIAS", "Férias"], "atestado": ["atestado", "Atestado", "ATESTADO MEDICO"],
                 "licenca_maternidade": ["licenca_maternidade", "Licença Maternidade"]}
    contagem = {"repetido": 0, "fim_antes_do_inicio": 0, "sem_fim": 0}
    por_matricula: dict[int, list] = {}
    for r in registros:
        item = {"tipo": random.choice(variantes[r["tipo"]]), "inicio": r["inicio"].isoformat(), "fim": r["fim"].isoformat(), "cid": r["cid"]}
        sorteio = rng.random()
        if sorteio < 0.004:
            item["inicio"], item["fim"] = item["fim"], item["inicio"]
            if item["inicio"] != item["fim"]:
                contagem["fim_antes_do_inicio"] += 1
        elif sorteio < 0.008:
            item["fim"] = None
            contagem["sem_fim"] += 1
        por_matricula.setdefault(r["matricula"], []).append(item)
        if 0.008 <= sorteio < 0.02:
            por_matricula[r["matricula"]].append(dict(item))
            contagem["repetido"] += 1
    pasta = RAW / "ponto"
    pasta.mkdir(parents=True, exist_ok=True)
    conteudo = [{"matricula": m, "afastamentos": lista} for m, lista in sorted(por_matricula.items())]
    (pasta / "afastamentos.json").write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")
    return contagem


def main() -> None:
    fotos, folha, fatos = simular()
    contagem = {"salario_digitado_errado": 0, "cpf_invalido": 0, "gestor_inexistente": 0, "admissao_no_futuro": 0, "linha_duplicada_antiga": 0}
    pasta = RAW / "rh"
    pasta.mkdir(parents=True, exist_ok=True)
    for mes, vinculos in fotos:
        df = sujar(pd.DataFrame([linha_da_foto(v, mes) for v in vinculos]), mes, contagem)
        (exportar_antigo if mes < MIGRACAO else exportar_novo)(df, pasta / f"colaboradores_{mes}.csv")
    exportar_folha(folha)
    sujeira_ponto = exportar_afastamentos(fatos["afastamentos"])

    empresa: Empresa = fatos["empresa"]
    todos = list(empresa.vinculos.values())
    inicio = MESES[0].start_time.date()
    saidas = [v for v in todos if v.desligamento]
    gabarito = {
        "headcount_por_mes": fatos["headcount"], "vinculos": len(todos), "pessoas": len({v.pessoa.cpf for v in todos}),
        "desligamentos": len(saidas), "voluntarios": sum(v.motivo == "Pedido de demissão" for v in saidas),
        "contratados_no_periodo": sum(v.admissao >= inicio for v in todos), "recontratacoes": empresa.recontratacoes,
        "desligamentos_silenciosos": fatos["silenciosos"], "pagos_apos_desligamento": fatos["fantasmas"], "ciclo_de_gestao": fatos["ciclo"],
        "gestor_problema": empresa.gestor_problema, "sujeira_fotos": contagem, "sujeira_ponto": sujeira_ponto,
    }
    EXTERNOS.mkdir(parents=True, exist_ok=True)
    (EXTERNOS / "gabarito.json").write_text(json.dumps(gabarito, ensure_ascii=False, indent=2), encoding="utf-8")
    print({k: v for k, v in gabarito.items() if k != "headcount_por_mes"})
    hc = fatos["headcount"]
    print("headcount", list(hc.values())[::5], "folha", len(folha))


if __name__ == "__main__":
    main()
