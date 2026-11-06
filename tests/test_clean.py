import pandas as pd

from src.clean import chave, cpf_valido, limpar_afastamentos, limpar_folha, limpar_foto
from src.settings import carregar

COMPETENCIA = pd.Timestamp("2024-03-01")
CPF_COM_ZERO = "01234567890"


def _linha(**campos):
    base = {"matricula": 1, "nome": "  JOAO   SA ", "cpf": "111.444.777-35", "nascimento": pd.Timestamp("1990-01-01"), "genero": "Masculino",
            "admissao": pd.Timestamp("2020-01-01"), "desligamento": pd.NaT, "motivo": "", "cargo": "ATENDENTE JR", "area": "CUSTOMER SUCCESS",
            "unidade": "SAO PAULO", "gestor": 2, "salario": 2500.0, "contrato": "TEMPORARIO", "inicio_vigencia": pd.Timestamp("2020-01-01")}
    return {**base, **campos}


def _limpar(catalogo, *linhas):
    return limpar_foto(pd.DataFrame(linhas), catalogo, COMPETENCIA)


def test_cpf_valido_confere_os_digitos():
    assert cpf_valido("11144477735")
    assert not cpf_valido("11144477736") and not cpf_valido("11111111111") and not cpf_valido("123")


def test_chave_ignora_acento_caixa_e_espacos():
    assert chave("  São   Paulo ") == "SAO PAULO"


def test_grafias_dos_dois_sistemas_viram_o_mesmo_cadastro(catalogo):
    limpos, quarentena = _limpar(catalogo, _linha())
    linha = limpos.iloc[0]
    assert quarentena.empty
    assert (linha["cargo"], linha["departamento"], linha["departamento_nome"]) == ("Atendente Júnior", "ATENDIMENTO", "Customer Success")
    assert (linha["unidade"], linha["contrato"], linha["genero"], linha["nome"]) == ("São Paulo", "Temporário", "M", "JOAO SA")


def test_cpf_sem_zero_a_esquerda_e_recuperado(catalogo):
    limpos, _ = _limpar(catalogo, _linha(cpf="52998224725"), _linha(matricula=2, cpf=CPF_COM_ZERO.lstrip("0")))
    assert set(limpos["cpf"]) == {"52998224725", CPF_COM_ZERO}


def test_linha_duplicada_fica_com_a_vigencia_mais_recente(catalogo):
    limpos, quarentena = _limpar(catalogo, _linha(salario=2500.0, inicio_vigencia=pd.Timestamp("2024-02-01")),
                                 _linha(salario=2400.0, inicio_vigencia=pd.Timestamp("2024-01-01")))
    assert limpos["salario"].tolist() == [2500.0]
    assert quarentena["motivo"].tolist() == ["linha_duplicada_antiga"]


def test_rejeicoes_ficam_na_quarentena_com_motivo(catalogo):
    _, quarentena = _limpar(catalogo, _linha(matricula=1, cpf="11144477700"), _linha(matricula=2, cargo="ASTRONAUTA"),
                            _linha(matricula=3, salario=25000.0), _linha(matricula=4, admissao=pd.Timestamp("2031-01-01")))
    assert set(quarentena["motivo"]) == {"cpf_invalido", "cargo_desconhecido", "salario_fora_da_faixa", "admissao_no_futuro"}


def test_quarentena_nao_guarda_nome_nem_cpf(catalogo):
    _, quarentena = _limpar(catalogo, _linha(cpf="11144477700"))
    assert not {"nome", "cpf", "nascimento"} & set(quarentena.columns)


def test_folha_repetida_e_removida():
    df = pd.DataFrame({"matricula": [1, 1, 2], "competencia": ["a", "a", "a"]})
    limpa, repetidas = limpar_folha(df)
    assert len(limpa) == 2 and repetidas == 1


def test_afastamentos_unificam_tipo_e_separam_problemas():
    datas = pd.to_datetime
    df = pd.DataFrame({"matricula": [1, 1, 2, 3], "tipo": ["FERIAS", "Férias", "ATESTADO MEDICO", "atestado"],
                       "inicio": datas(["2024-01-01", "2024-01-01", "2024-02-05", "2024-03-01"]),
                       "fim": datas(["2024-01-10", "2024-01-10", "2024-02-01", None])})
    limpos, rejeitados = limpar_afastamentos(df, carregar()["afastamentos"])
    assert limpos["tipo"].tolist() == ["ferias"]
    assert set(rejeitados["motivo"]) == {"repetido", "fim_antes_do_inicio", "sem_data_fim"}
