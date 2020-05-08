import numpy as np
import math
from utils import lsqnonneg

'''

Corresponds with ELMM_ADMM.m from the toolbox at following link:
https://openremotesensing.net/knowledgebase/spectral-variability-and-extended-linear-mixing-model/

   The algorithm is presented in detail in:

   L. Drumetz, M. A. Veganzones, S. Henrot, R. Phlypo, J. Chanussot and 
   C. Jutten, "Blind Hyperspectral Unmixing Using an Extended Linear
   Mixing Model to Address Spectral Variability," in IEEE Transactions on 
   Image Processing, vol. 25, no. 8, pp. 3890-3905, Aug. 2016.

'''
    
def elmm_admm( data, A_init, psis_init, S0, lambda_s, lambda_a, lambda_psi, **kwargs):
    '''
    Unmix hyperspectral data using the Extended Linear Mixing Model    

     Mandatory inputs:
    -data: m*n*L image cube, where m is the number of rows, n the number of
    columns, and L the number of spectral bands.
    -A_init: P*N initial abundance matrix, with P the number of endmembers
    to consider, and N the number of pixels (N=m*n)
    -psis_init: P*N initial scaling factor matrix
    -S0: L*P reference endmember matrix
    -lambda_s: regularization parameter on the ELMM tightness
    -lambda_a: regularization parameter for the spatial regularization on
    the abundances.
    -lambda_psi: regularization parameter for the spatial regularization on
    the scaling factors
    The spatial regularization parameters can be scalars, in which case 
    they will apply in the same way for all the terms of the concerned
    regularizations. If they are vectors, then each term of the sum
    (corresponding to each material) will be differently weighted by the
    different entries of the vector.

   Optional inputs (arguments are to be provided in the same order as in 
    the following list):
    -norm_sr: choose norm to use for the spatial regularization on the
    abundances. Can be '2,1' (Tikhonov like penalty on the gradient) or
    '1,1' (Total Variation) (default: '1,1')
    -verbose: flag for display in console. Display if true, no display
    otherwise (default: true)
    -maxiter_anls: maximum number of iterations for the ANLS loop (default:
    100)
    -maxiter_admm: maximum number of iterations for the ADMM loop (default:
    100)
    -epsilon_s: tolerance on the relative variation of S between two
    consecutive iterations (default: 10^(-3))
    -epsilon_a: tolerance on the relative variation of A between two
    consecutive iterations (default: 10^(-3))
    -epsilon_psi: tolerance on the relative variation of psi between two
    consecutive iterations (default: 10^(-3))
    -epsilon_admm_abs: tolerance on the absolute part of the primal and
    dual residuals (default: 10^(-2))
    -epsilon_admm_rel: tolerance on the relative part of the primal and
    dual residuals (default: 10^(-2))

   Outputs:
    -A: P*N abundance matrix
    -psi_maps: P*N scaling factor matrix
    -S: L*P*N tensor constaining all the endmember matrices for each pixel
    -optim_struct: structure containing the values of the objective
    function and its different terms at each iteration
    '''
 
    norm_sr = kwargs.get('norm_sr', '1,1')
    verbose = kwargs.get('verbose', True)
    maxiter_anls = kwargs.get('maxiter_anls', 100)
    maxiter_admm = kwargs.get('maxiter_admm', 100)
    epsilon_s = kwargs.get('epsilon_s', 10**(-3))
    epsilon_a = kwargs.get('epsilon_a', 10**(-3))
    epsilon_psi = kwargs.get('epsilon_psi', 10**(-3))
    epsilon_admm_abs = kwargs.get('epsilon_admm_abs', 10**(-2))
    epsilon_admm_rel = kwargs.get('epsilon_admm_rel', 10**(-2))



    P = A_init.shape[0]  # number of endmembers

    scalar_lambda_a = False
    scalar_lambda_psi = False
    
    if lambda_a.shape[1] == 1:
        scalar_lambda_a = True
    elif lambda_a.shape[1] == P:
        
        if lambda_a.shape[0] == 1:
            lambda_a = lamdba_a.transpose()
    else:
        raise ValueError('lambda_a must be a scalar or a P-dimensional vector')

    if lambda_psi.shape[1] == 1:
        scalar_lambda_psi = True
    elif lambda_psi.shape[1] == P:
        if lambda_psi.shape[0] == 1:
            lambda_psi = lamdba_psi.transpose()
    else:
        raise ValueError('lambda_psi must be a scalar or a P-dimensional vector')


    m, n, L = data.shape
    N = m*n

    # data_r = data.reshape((N, L)).transpose()
    data_r = np.reshape( np.copy(data), (N, L) ).transpose()
    
    rs = np.zeros((maxiter_anls,1))
    ra = np.zeros((maxiter_anls,1))
    rpsi = np.zeros((maxiter_anls,1))

    A = A_init
    S = np.tile( S0, [1,1,N] )
    psi_maps = psis_init

    S0ptS0 = np.diag(S0.transpose()*S0)
    
    if scalar_lambda_a:
        TV_a = np.zeros((maxiter_anls,1))
    else:
        TV_a = np.zeros((maxiter_anls,P))

    if scalar_lambda_psi:
        smooth_psi = np.zeros((maxiter_anls,1))
    else:
        smooth_psi = np.zeros((maxiter_anls,P))

    # forward first order horizontal difference operator
    FDh = np.zeros((m,n))
    FDh[0, n-1] = -1
    FDh[m-1,n-1] = 1
    FDh = np.fft.fft2(FDh)
    FDhC = np.conj(FDh)

    # forward first order vertical  difference operator
    FDv = np.zeros((m,n))
    FDv[0, n-1] = -1
    FDv[m-1,n-1] = 1;
    FDv = np.fft.fft2(FDh)
    FDvC = np.conj(FDh)

    # barrier parameter of ADMM and related
    rho = np.zeros((maxiter_admm,1))
    rho[0] = 10
    tau_incr = 2
    tau_decr = 2
    nu = 10


    # EXPECTED BUG: matrix vs element multiplication
    for i in range(maxiter_anls):
        S_old = np.copy(S)
        psi_maps_old = np.copy(psi_maps)
        A_old_anls = np.copy(A)
        # print('updating S...' if verbose)
        
        #S_update
        for k in range(N):
            first_op = np.multiply(data_r[:,k], A[:,k].transpose()) + np.multiply(np.multiply(lambda_s, S0), np.diag(psi_maps[:,k]))
            second_op = np.multiply(A[:,k], A[:,k].transpose()) + np.multiply(lambda_s,np.identity(P))
            S[:,:,k] = np.divide(first_op, second_op)
            S[:,:,k] = np.max(pow(10,-6), S[:,:,k])


        # A_update

        if np.any( lambda_a ):
            # initialize split variables
            v1 = A
            v1_im = conv2im(v1,m,n,P)
            v2 = ConvC(A,FDh,m,n,P)
            v3 = ConvC(A,FDv,m,n,P)
            v4 = A

            # initialize Lagrange multipliers
            d1 = np.zeros((P,N))
            d2 = np.zeros((v2.shape))
            d3 = np.zeros((v3.shape))
            d4 = np.zeros((psi_maps.shape))

            mu = np.zeros((1,N))

            # initialize primal and dual variables
            primal = np.zeros(maxiter_admm,1)
            dual = np.zeros(maxiter_admm,1)

            # precomputing
            Hvv1 = ConvC(v1,FDv,m,n,P)
            Hhv1 = ConvC(v1,FDh,m,n,P)

            for j in range(maxiter_admm):
                A_old = A
                v1_old = v1
                p_res2_old = v2 - Hhv1;
                p_res3_old = v3 - Hvv1
                v4_old = v4
                d1_old = d1
                d4_old = d4

                for k in range(N):
                    ALPHA = S[:,:,k].transpose()*S[:,:,k]+2*rho[j]*identity(P)
                    ALPHA_INVERTED = np.linalg.inv(ALPHA)
                    BETA = np.ones((P,1))
                    s = ALPHA_INVERTED.sum(axis=0)
                    SEC_MEMBER = np.concatenate(( S[:,:,k].transpose()*data_r[:,k] + rho[j]*(v1[:,k]+d1[:,k]+v4[:,k]+d4[:k]), 1), axis=0)
                    OMEGA_INV = np.concatenate(( (ALPHA_INVERTED*(identity(P)-1/s*np.ones((P,P))*ALPHA_INVERTED), 1/s * ALPHA_INVERTED * BETA), (1/s*BETA.transpose()*ALPHA_INVERTED, -1/s)), axis=0) # TODO: concatenate must mirror matlab
                    X = OMEGA_INV * SEC_MEMBER

                    A[:,k] = X[0:-2]
                    mu[k] = X[-1]

                A_im = conv2im(A,m,n,P)
                d1_im = conv2im(d1,m,n,P)
                d2_im = conv2im(d2,m,n,P)
                d3_im = conv2im(d3,m,n,P)
                v2_im = conv2im(v2,m,n,P)
                v3_im = conv2im(v3,m,n,P)

                # update in the Fourier domain

                for p in range(P):
                    sec_spectral_term = np.fft.fft2(np.squeeze(A_im[:,:,p]) - np.squeeze(d1_im[:,:,p])) + np.fft.fft2(np.squeeze((v2_im[:,:,p]+np.squeeze(d2_im[:,:,p])))*FDhC + np.fft.fft2(np.squeeze(v3_im[:,:,p]+np.squeeze(d3_im[:,:,p]))))*FDvC
                    v1_im[:,:,p] = np.real(np.ftt.ifft2((sec_spectral_term)/(np.ones((m,n)) + abs(FDh)**2 + abs(FDv)**2)))


                # convert back necessary variables into matrices

                v1 = conv2mat(v1_im)
                Hvv1 = ConvC(v1,FDv)
                Hhv1 = ConvC(v1, FDh)


                # min w.r.t. v2 and v3

                if scalar_lambda_a:
                    if norm_sr == '2,1':
                        v2 = vector_soft_col( -(d2-Hhv1), lambda_a/rho[j])
                        v3 = vector_soft_col( -(d3-Hvv1), lambda_a/rho[j])
                    elif norm_sr == '1,1':
                        v2 = soft( -(d2-Hhv1), lambda_a/rho[j])
                        v3 = soft( -(d3-Hvv1), lambda_a/rho[j])
                else:
                    if norm_sr == '2,1':
                        for p in range(P):
                            v2[p,:] = vector_soft_col(-(d2[p,:] - Hhv1[p,:]), lambda_a[p]/rho[j])
                            v3[p,:] = vector_soft_col(-(d3[p,:] - Hvv1[p,:]), lambda_a[p]/rho[j])
                    elif norm_sr == '1,1':
                            v2[p,:] = soft(-(d2[p,:] - Hhv1[p,:]), lambda_a[p]/rho[j])
                            v3[p,:] = soft(-(d3[p,:] - Hvv1[p,:]), lambda_a[p]/rho[j])

                            
                # min w.r.t. v4

                v4 = max(A-d4, np.zeros(A.shape))


                # dual update
                # compute necessary variables for the residuals and update lagrange multipliers
                p_res1 = v1 - A;
                p_res2 = v2 - Hhv1;
                p_res3 = v3 - Hvv1;
                p_res4 = v4 - A;
                
                d1 = d1 + p_res1;
                d2 = d2 + p_res2;
                d3 = d3 + p_res3;
                d4 = d4 + p_res4;


                # primal and dual residuals

                primal[j] = math.sqrt( np.linalg.norm(p_res1, 'fro')**2 + np.linalg.norm(p_res2, 'fro')**2 + np.linalg.norm(p_res3, 'fro')**2 + np.linalg.norm(p_res4, 'fro')**2 )
                dual[j] = rho[j] * math.sqrt( np.linalg.norm(v1_old-v1,'fro')**2 + np.linalg.norm(v4_old-v4,'fro')**2 )

                # compute termination values

                epsilon_primal = math.sqrt(4*P*N) * epsilon_admm_abs + epsilon_admm_rel*max(math.sqrt(2*np.linalg.norm(A,'fro')**2), math.sqrt(np.linalg.norm(v1_old,'fro')**2 + np.linalg.norm(p_res2_old,'fro')**2 + np.linalg.norm(p_res3_old,'fro')**2 + np.linalg.norm(v4_old,'fro')**2))
                epsilon_dual = math.sqrt(P*N)*epsilon_admm_abs + rho[j] * epsilon_admm_rel * math.sqrt(np.linalg.norm(d1_old,'fro')+np.linalg.norm(d4_old,'fro')**2)

                rel_A = abs(np.linalg.norm(A,'fro')-np.linalg.norm(A_old,'fro'))/np.linalg.norm(A_old,'fro')


                # display of admm results

                if verbose:
                    print(f'iter {j}, rel_A = {rel_A}, primal = {primal[j]}, eps_p = {epsilon_primal}, dual = {dual[j]}, eps_d = {epsilon_dual}, rho = {rho[j]}')

                if j > 1 and ((primal[j] < epsilon_primal and dual[j] < epsilon_dual)):
                    break


                # rho update

                if j < maxiter_admm:
                    if np.norm(primal[j]) > nu*np.norm(dual[j]):
                        rho[j+1] = tau_incr*rho[j]
                        A = A/tau_incr
                    elif np.norm(dual[j]) < nu*np.norm(primal[j]):
                        rho[j+1] = rho[j]/tau_decr
                        A = tau_decr * A
                    else:
                        rho[j+1] = rho[j]

            # end for loop

        else:
            # without spatial regularization
            for k in range(N):
                A[:,k] = FCLSU(data_r[:,k],S[:,:,k])


            if verbose:
                print("Done")
                print("updating psi..")

            # psi_update

            if any(lambda_psi):
                # with spatial regularization
                if scalar_lambda_psi:
                    for p in range(P):
                        numerator = 0 # TODO
                        psi_maps_im = np.real(np.fft.ifft2(np.fft.fft2(numerator)/((lambda_psi*(abs(FDh)**2+abs(FDv)**2)+lambda_s*S0ptS0[p]))))
                        psi_maps[p,:] = psi_maps_im[:]

                else:
                    for p in range(P):
                        numerator = 0 # TODO
                        psi_maps_im = np.real(np.fft.ifft2(np.fft.fft2(numerator)/((lambda_psi[p]*(abs(FDh)**2+abs(FDv)**2)+lambda_s*S0ptS0[p]))))
                        psi_maps[p,:] = psi_maps_im[:]
            else:
                for p in range(P):
                    psi_maps_temp = np.zeros((N,1))
                    for k in range(N):
                        psi_maps_temp[k] = (S0[:,p].transpose()*S[:,p,k])/S0ptS0[p]
                    psi_maps[p,:] = psi_maps_temp

            if verbose:
                print("Done")

                
            # residuals of the ANLS loops
            rs_vect = np.zeros((N,1))

            for k in range(N):
                rs_vect[k] = np.linalg.norm(np.squeeze(S[:,:,k])-np.squeeze(S_old[:,:,k]),'fro')/np.linalg.norm(np.squeeze(S_old[:,:,k]),'fro')

            rs[i] = rs_vect.mean(axis=0)
            ra[i] = np.linalg.norm(A[:]-A_old_anls[:],2)/np.linalg.norm(A_old_anls[:],2)
            rpsi[i] = np.linalg.norm(psi_maps-psi_maps_old,'fro')/(norm(psi_maps_old,'fro'))

            # compute objective function value

            SkAk = np.zeros((L,N))
            for k in range(N):
                SkAk[:,k] = np.squeeze(S[:,:,k]*A[:,k])
                S0_psi[:,:,k] = S0*np.diag(psi_maps[:,k])

            norm_fitting[i] = 1/2*np.norm(data_r[:]-SkAk[:])**2

            source_model[i] = 1/2*np.norm(S[:]-S0_psi[:])**2

            if any(lambda_psi) and any(lambda_a):  # different objective functions depending on the chosen regularizations
                if scalar_lambda_psi:
                    smooth_psi[i] = 1/2*(sum(sum((ConvC(psi_maps,FDh,m,n,P)**2))) + sum(sum((ConvC(psi_maps,FDv,m,n,P)**2))))
                else:
                    CvCpsih = ConvC(psi_maps,FDh,m,n,P)
                    CvCpsiv = ConvC(psi_maps,FDv,m,n,P)
                    for p in range(P):
                        smooth_psi[i,p] = 1/2*(sum(sum((CvCpsih[p,:h]**2))) + sum(sum((CVCpsiv[p,:]**2))))


                if scalar_lambda_a:
                    if norm_sr == '2,1':
                        TV_a[i] = sum(sum(math.sqrt(ConvC(A,FDh,m,n,P)**2 + ConvC(A,FDv,m,n,P)**2)))
                    elif norm_sr == '1,1':
                        TV_a[i] = sum(sum(abs(ConvC(A,FDh,m,n,P)) + abs(ConvC(A,FDv,m,n,P))))
                else:
                    CvCAh = ConvC(A,FDh,m,n,P)
                    CvCAv = ConvC(A,FDv,m,n,P)

                    if norm_sr == '2,1':
                        for p in range(P):
                            TV_a[i,p] = sum(sum(math.sqrt(CvCAh[p,:]**2 + CvCAv[p,:]**2)))
                    elif norm_sr == '1,1':
                        for p in range(P):
                            TV_a[i,p] = sum(sum(abs(CvCAh[p,:])+abs(CvCAv[p,h])))

                objective[i] = norm_fitting[i] + lambda_s * source_model[i] + lambda_a.transpose() * TV_a[i,:].transpose() + lambda_psi.transpose * smooth_psi[i,:].transpose()

            elif not(any(lambda_psi)) and any(lambda_a):

                if scalar_lambda_a:
                    if norm_sr == '2,1':
                        TV_a[i] = sum(sum(math.sqrt(ConvC(A,FDh,m,n,P)**2 + ConvC(A,FDv,m,n,P)**2)))
                    elif norm_sr == '1,1':
                        TV_a[i] = sum(sum(abs(ConvC(A,FDh,m,n,P)) + abs(ConvC(A,FDv,m,n,P))))
                else:
                    CvCAh = ConvC(A,FDh,m,n,P)
                    CvCAv = ConvC(A,FDv,m,n,P)

                    if norm_sr == '2,1':
                        for p in range(P):
                            TV_a[i,p] = sum(sum(math.sqrt(CvCAh[p,:]**2 + CvCAv[p,:]**2)))
                    elif norm_sr == '1,1':
                        for p in range(P):
                            TV_a[i,p] = sum(sum(abs(CvCAh[p,:])+abs(CvCAv[p,h])))


                objective[i] = norm_fitting[i] + lambda_s * source_model[i] + lambda_a.transpose() * TV_a[i,:].transpose()


            elif any(lambda_psi) and not(any(lambda_a)):
                if scalar_lambda_psi:
                    smooth_psi[i] = 1/2*(sum(sum((ConvC(psi_maps,FDh,m,n,P)**2))) + sum(sum((ConvC(psi_maps,FDv,m,n,P)**2))))
                else:
                    CvCpsih = ConvC(psi_maps,FDh,m,n,P)
                    CvCpsiv = ConvC(psi_maps,FDv,m,n,P)
                    for p in range(P):
                        smooth_psi[i,p] = 1/2*(sum(sum((CvCpsih[p,:h]**2))) + sum(sum((CVCpsiv[p,:]**2))))

                objective[i] = norm_fitting[i] + lambda_s * source_model[i] + lambda_psi.transpose() * smooth_psi[i,:].transpose()

            else:
                objective[i] = norm_fitting[i] + lambda_s * source_model[i]

            # termination test
            if (rs[i] < epsilon_s) and (ra[i] < espilon_a) and (rpsi[i] < epsilon_psi):
                break
                            


    # gather processed output

    '''
    Outputs:
    -A: P*N abundance matrix
    -psi_maps: P*N scaling factor matrix
    -S: L*P*N tensor constaining all the endmember matrices for each pixel
    -optim_struct: structure containing the values of the objective
    function and its different terms at each iteration
    '''

    outputs = []
    outputs.append(A)
    outputs.append(psi_maps)
    outputs.append(S)
    

    return outputs

# auxiliary functions


#Fully Constrained Linear Spectral Unmixing
def FCLSU(HIM,M):
    ns = HIM.shape[1]
    l = M.shape[0]
    p = M.shape[1]
    Delta = 1/1000
    N = np.zeros((l+1,p))
    N[1:l,1:p] = Delta*M
    N[l+1,:] = np.ones((1,p))
    s = np.zeros((l+1,1))
    
    out = np.zeros((ns,p))

    for i in range(ns):
        s[1:l] = Delta*HIM[:,i]
        s[1:l] = 1
        Abundances = lsqnonneg(N,s)
        out[i,:] = Abundances
    return out

# circular convolution
def ConvC(X, FK, m, n, P):
    # likely area for a bug
    
    # matlab:
    # reshape(real(ifft2(fft2(reshape(X', m,n,P)).*repmat(FK,[1,1,P]))), m*n,P)';
    # python:
    # np.real(np.fft.ifft2(np.fft.fft2(X.transpose().reshape((m,n,P)))*np.kron(np.ones((1,1,P)),FK))).reshape((m*n,P)).transpose()

    first_op = np.fft.fft2(X.transpose().reshape((m,n,P)))
    second_op = np.real( np.fft.ifft2( first_op * np.kron( np.ones((1,1,P)), FK) ))
    third_op = second_op.reshape((m*n, P)).transpose()
    return third_op

# convert matrix to image
def conv2im(A, m, n, P):
    return A.transpose().reshape((m,n,P))

# convert image to matrix
def conv2mat(A, m, n, P):
    return A.reshape((m*n,P)).transpose()

# soft-thresholding function
def soft(x, T):
    if np.sum(abs(T.flatten(1))) == 0:
        y = x
    else:
        y = max(abs(x)-T, 0)
        y = y/(y+T) * x
    return y

# computes the vector soft columnwise
def vector_soft_col(X, tau):
    NU = math.sqrt(sum(X**2))
    A = max(0,NU-tau)
    Y = np.kron(np.ones((size(X, axis=1),1)), (A/(A+tau))) * X
    return Y


if __name__ == '__main__':
    m = 5
    n = 5
    L = 5
    P = 5
    N = m * n

    arb = 5
    
    data = np.zeros((n,n,L))
    A_init = np.zeros((P, N))
    psis_init = np.zeros((P, N))
    S0 = np.zeros((L, P))
    lambda_s = np.zeros((arb,arb))
    lambda_a = np.zeros((arb,arb))
    lambda_psi = np.zeros((arb,arb))
    
    output = elmm_admm( data, A_init, psis_init, S0, lambda_s, lambda_a, lambda_psi )

    print( output )

