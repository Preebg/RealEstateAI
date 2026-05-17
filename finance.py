import ctypes
import os
import platform

# Load the shared library
lib_name = "finance.so" if platform.system() != "Windows" else "finance.dll"
lib_path = os.path.join(os.path.dirname(__file__), lib_name)
try:
    _lib = ctypes.CDLL(lib_path)
except OSError:
    _lib = None

def calculate_10yr_appreciation(current_value, location_score):
    if not _lib: raise RuntimeError("C++ finance library not compiled. Run: g++ -shared -fPIC -o finance.so finance.cpp")
    f_val, a_rate, t_growth = ctypes.c_double(), ctypes.c_double(), ctypes.c_double()
    _lib.calculate_10yr_appreciation(ctypes.c_double(current_value), ctypes.c_double(location_score), 
                                     ctypes.byref(f_val), ctypes.byref(a_rate), ctypes.byref(t_growth))
    return {"future_value": f_val.value, "annual_rate": a_rate.value, "total_growth": t_growth.value}

def calculate_mortgage(price, down_payment_pct, interest_rate, loan_term):
    if not _lib: raise RuntimeError("C++ finance library not compiled.")
    _lib.calculate_mortgage.restype = ctypes.c_double
    return _lib.calculate_mortgage(ctypes.c_double(price), ctypes.c_double(down_payment_pct), 
                                   ctypes.c_double(interest_rate), ctypes.c_int(loan_term))

def calculate_operating_expenses(price, tax_rate, monthly_insurance, monthly_hoa, maint_percent, monthly_rent, vacancy_reserve_pct, management_fee_pct):
    if not _lib: raise RuntimeError("C++ finance library not compiled.")
    total, taxes, maint, vac, mgmt = ctypes.c_double(), ctypes.c_double(), ctypes.c_double(), ctypes.c_double(), ctypes.c_double()
    _lib.calculate_operating_expenses(ctypes.c_double(price), ctypes.c_double(tax_rate), ctypes.c_double(monthly_insurance), 
                                      ctypes.c_double(monthly_hoa), ctypes.c_double(maint_percent), ctypes.c_double(monthly_rent), 
                                      ctypes.c_double(vacancy_reserve_pct), ctypes.c_double(management_fee_pct), 
                                      ctypes.byref(total), ctypes.byref(taxes), ctypes.byref(maint), ctypes.byref(vac), ctypes.byref(mgmt))
    return total.value, taxes.value, maint.value, vac.value, mgmt.value

def calculate_investment_metrics(price, annual_noi, total_investment, monthly_net_cash_flow):
    if not _lib: raise RuntimeError("C++ finance library not compiled.")
    cap, coc = ctypes.c_double(), ctypes.c_double()
    _lib.calculate_investment_metrics(ctypes.c_double(price), ctypes.c_double(annual_noi), 
                                      ctypes.c_double(total_investment), ctypes.c_double(monthly_net_cash_flow), 
                                      ctypes.byref(cap), ctypes.byref(coc))
    return cap.value, coc.value
