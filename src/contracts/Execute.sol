// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {ReentrancyGuard} from "lib/solmate/src/utils/ReentrancyGuard.sol";
import {Ownable} from "lib/solmate/src/auth/Owned.sol";
import {IERC20} from "lib/solmate/src/tokens/ERC20.sol";
//import {UniswapV2Router02} from "lib/solmate/src/protocols/uniswap/v2/UniswapV2Router02.sol";
import {UniversalRouter} from "lib/universal-router/contracts/interfaces/IUniversalRouter.sol";
import {IPoolAddressesProvider} from "aave-v3-core/contracts/interfaces/IPoolAddressesProvider.sol";
import {IPool} from "aave-v3-core/contracts/interfaces/IPool.sol";
import {IFlashLoanSimpleReceiver} from "lib/aave-v3-core/contracts/flashloan/interfaces/IFlashLoanSimpleReceiver.sol";
import {IERC721Receiver} from "lib/openzeppelin-contracts/contracts/interfaces/IERC721Receiver.sol";

contract FlashArbitrage is IFlashLoanSimpleReceiver, ReentrancyGuard, Ownable {
    // State variables
    mapping(address => bool) public allowedTokens;
    mapping(address => uint8) public tokenDecimals;
    mapping(address => bool) public authorizedAddresses;
    mapping(address => mapping(address => uint256)) public reserves;
    mapping(address => mapping(address => uint256)) public tokenBalances;
    mapping(address => mapping(address => uint256)) public tokenAllowances;
    mapping(address => bool) public allowedProtocols;
    address[] public allowedTokensList;
    address[] public allowedProtocolsList;
    address public uniswapV2Router;
    IPoolAddressesProvider public immutable ADDRESSES_PROVIDER;
    IPool public immutable POOL;
    bool public executionPaused;

    // Events
    event TokenAdded(address indexed token, uint8 decimals);
    event TokenRemoved(address indexed token);
    event ProtocolAdded(address indexed protocol);
    event ProtocolRemoved(address indexed protocol);
    event ArbitrageExecuted(
        address indexed executor,
        address[] path,
        uint256 amountIn,
        uint256 amountOut,
        uint256 profit
    );
    event ContractInitialized(address indexed owner, uint256 timestamp);
    event ExecutionPaused(bool paused);
    event ExecutionResumed(bool resumed);

    // Modifiers
    modifier onlyAuthorized() {
        require(authorizedAddresses[msg.sender], "Not authorized");
        _;
    }


    // Constructor
    constructor(address _provider) {
        ADDRESSES_PROVIDER = IPoolAddressesProvider(_provider);
        POOL = IPool(ADDRESSES_PROVIDER.getPool());

        authorizedAddresses[msg.sender] = true;
        executionPaused = false;

        _addProtocol(0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f); // Uniswap V2 Router (replace if needed)

    emit ContractInitialized(msg.sender, block.timestamp);
}


    // Token Management
    function _addToken(address token, uint8 decimals) internal {
        require(token != address(0), "Invalid token address");
        require(!allowedTokens[token], "Token already added");
        
        allowedTokens[token] = true;
        tokenDecimals[token] = decimals;
        allowedTokensList.push(token);
        
        emit TokenAdded(token, decimals);
    }

    function addToken(address token, uint8 decimals) external onlyOwner {
        _addToken(token, decimals);
    }

    function removeToken(address token) external onlyOwner {
        require(allowedTokens[token], "Token not allowed");
        require(token != address(0), "Cannot remove ETH");
        
        allowedTokens[token] = false;
        emit TokenRemoved(token);
    }

    // Protocol Management
    function _addProtocol(address protocol) internal {
        require(protocol != address(0), "Invalid protocol address");
        require(!allowedProtocols[protocol], "Protocol already added");
        
        allowedProtocols[protocol] = true;
        allowedProtocolsList.push(protocol);
        emit ProtocolAdded(protocol);
    }

    function addProtocol(address protocol) external onlyOwner {
        _addProtocol(protocol);
    }

    function removeProtocol(address protocol) external onlyOwner {
        require(allowedProtocols[protocol], "Protocol not allowed");
        require(protocol != address(0), "Cannot remove ETH");
        
        allowedProtocols[protocol] = false;
        emit ProtocolRemoved(protocol);
    }

    // Token Operations
    function depositTokens(address token, uint256 amount) external {
        require(allowedTokens[token], "Token not allowed");
        require(!executionPaused, "Contract paused");
        
        if (token != address(0)) {
            require(tokenAllowances[token][msg.sender] >= amount, "Insufficient allowance");
            IERC20(token).transferFrom(msg.sender, address(this), amount);
        } else {
            require(msg.value == amount, "Invalid ETH amount");
        }
        
        tokenBalances[token][msg.sender] += amount;
    }

    function withdrawTokens(address token, uint256 amount) external {
        require(allowedTokens[token], "Token not allowed");
        require(tokenBalances[token][msg.sender] >= amount, "Insufficient balance");
        
        tokenBalances[token][msg.sender] -= amount;
        if (token != address(0)) {
            IERC20(token).transfer(msg.sender, amount);
        } else {
            payable(msg.sender).transfer(amount);
        }
    }

    function initiateFlashLoan(address asset, uint256 amount, bytes calldata arbitrageParams) external onlyAuthorized {
        require(!executionPaused, "Execution paused");

        POOL.flashLoanSimple(
            address(this),
            asset,
            amount,
            arbitrageParams,
            0 // referralCode
        );
    }
    // Arbitrage Execution
    function executeArbitrage(
        address[] calldata path,
        uint256 amountIn,
        uint256 minProfit
    ) external onlyAuthorized returns (uint256 profit) {
        require(!executionPaused, "Contract paused");
        require(path.length >= 2, "Invalid path length");
        require(allowedProtocols[path[0]], "Invalid protocol");
        
        uint256 initialBalance = tokenBalances[path[0]][msg.sender];
        require(initialBalance >= amountIn, "Insufficient balance");
        
        tokenBalances[path[0]][msg.sender] -= amountIn;
        
        // Execute arbitrage
        uint256 finalBalance = _executeArbitrage(path, amountIn);
        
        profit = finalBalance - amountIn;
        require(profit >= minProfit, "Insufficient profit");
        
        tokenBalances[path[0]][msg.sender] += finalBalance;
        
        emit ArbitrageExecuted(msg.sender, path, amountIn, finalBalance, profit);
    }

    function _executeArbitrage(address[] memory path, uint256 amountIn) internal returns (uint256) {
        uint256 balance = amountIn;
        
        for (uint256 i = 0; i < path.length - 1; i++) {
            balance = _swap(path[i], path[i + 1], balance);
        }
        
        return balance;
    }

    function _swap(
        address tokenIn,
        address tokenOut,
        uint256 amountIn
    ) internal returns (uint256 amountOut) {

        // Create a path of length 2, directly from tokenIn to tokenOut
        address[] memory path = new address[](2);
        path[0] = tokenIn;
        path[1] = tokenOut;

        // Make the swap
        uint256 amountReceived;
            if (tokenIn == address(0)) {
            // ETH to token swap
            amountReceived = IUniswapV2Router02(uniswapV2Router)
            .swapExactETHForTokensSupportingFeeOnTransferTokens(
                0, // amountOutMin
                path,
                address(this),
                block.timestamp
                )[path.length - 1];
    } else if (tokenOut == address(0)) {
        // Token to ETH swap
        IERC20(tokenIn).approve(uniswapV2Router, amountIn);
        amountReceived = IUniswapV2Router02(uniswapV2Router)
            .swapExactTokensForETHSupportingFeeOnTransferTokens(
                amountIn,
                0, // amountOutMin
                path,
                address(this),
                block.timestamp
                )[path.length - 1];
    } else {
        // Token to token swap
        IERC20(tokenIn).approve(uniswapV2Router, amountIn);
        amountReceived = IUniswapV2Router02(uniswapV2Router)
            .swapExactTokensForTokensSupportingFeeOnTransferTokens(
                amountIn,
                0, // amountOutMin
                path,
                address(this),
                block.timestamp
            )[path.length - 1];
    }

    return amountReceived;
}

    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata params
    ) external override returns (bool) {
        require(msg.sender == address(POOL), "Unauthorized flash loan sender");
        require(initiator == address(this), "Only this contract can initiate");

        // Decode path and minimum profit from params
        (address[] memory path, uint256 minProfit) = abi.decode(params, (address[], uint256));

        uint256 profit = _executeArbitrage(path, amount);
        require(profit >= minProfit, "Unprofitable arbitrage");

        // Approve the pool to pull the owed amount (flash loan + fee)
        IERC20(asset).approve(address(POOL), amount + premium);

    return true;
}
    // Administrative Functions
    function pauseExecution() external onlyOwner {
        executionPaused = true;
        emit ExecutionPaused(true);
    }

    function resumeExecution() external onlyOwner {
        executionPaused = false;
        emit ExecutionResumed(true);
    }

    // Authorization Management
    function authorizeAddress(address _address) external onlyOwner {
        require(_address != address(0), "Invalid address");
        authorizedAddresses[_address] = true;
    }

    function revokeAuthorization(address _address) external onlyOwner {
        require(authorizedAddresses[_address], "Address not authorized");
        authorizedAddresses[_address] = false;
    }

    // View Functions
    function getTokenBalance(address token, address user) external view returns (uint256) {
        return tokenBalances[token][user];
    }

    function getAllowedTokens() external view returns (address[] memory) {
        return allowedTokensList;
    }

    function getAllowedProtocols() external view returns (address[] memory) {
        return allowedProtocolsList;
    }

    // Fallback function
    receive() external payable {}
}
